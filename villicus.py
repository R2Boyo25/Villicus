from flask import *
from flask_sock import Sock

import toml
import json
import os
import subprocess
import logging
import click
import sys
import time
from fcntl import fcntl, F_GETFL, F_SETFL
from os import O_NONBLOCK, read
import signal
import threading
from datetime import datetime

app = Flask("Villicus")
sock = Sock(app)

app.config.update(
    staticdir="static",
    configfile=os.path.expanduser("~/.config/villicus.toml"),
    configdir=os.path.expanduser("~/.config/villicus/"),
)

#### Disable Logging ####

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


def secho(text, file=None, nl=None, err=None, color=None, **styles):
    pass


def echo(text, file=None, nl=None, err=None, color=None, **styles):
    pass


# click.echo = echo
# click.secho = secho

#### Disable Logging ####

websockets = []
LASTUPDATE = datetime(year=1, month=1, day=1)

cfg = {}


class Proc:
    def __init__(self, name, dct):
        self.name = name
        self.dct = dct
        self.process = None
        self.env = os.environ.copy()
        self.paused = False
        self.curout = []

        if "start" not in self.dct:
            self.start()
            return

        if self.dct["start"]:
            self.start()

    def start(self):
        proc = self.dct

        if "command" not in proc:
            return

        command = proc["command"]
        workdir = proc["workdir"] if "workdir" in proc else os.getcwd()

        if "env" in proc:
            for var in proc["env"].keys():
                self.env[var] = proc["env"][var]

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=workdir,
            env=self.env,
            shell=True,
            preexec_fn=os.setsid,
        )

        if not self.process:
            return

        flags = fcntl(self.process.stdout, F_GETFL)
        fcntl(self.process.stdout, F_SETFL, flags | O_NONBLOCK)

    def kill(self):
        if not self.process:
            return

        try:
            os.killpg(self.process.pid, signal.SIGTERM)

        except ProcessLookupError:
            pass

    @property
    def out(self):
        if self.process is None:
            return ""

        while 1:
            tmp = self.process.stdout.readline()

            if not tmp:
                break

            self.curout.append(tmp.decode().strip("\n"))

            if not self.process.poll() and not tmp:
                break

        return "\n".join(self.curout)

    @property
    def running(self):
        if not self.paused:
            if self.process is not None:
                return self.process.poll() is None

            else:
                return False

        else:
            return True

    @property
    def returncode(self):
        if self.process is None:
            return -111

        returncode = self.process.returncode
        return returncode if returncode is not None else -111


class Procs:
    def __init__(self):
        self.dct = {}

    def start(self, name, dct=None):
        if dct:
            if name in self.dct.keys():
                if self.dct[name].running:
                    self.dct[name].kill()

            self.dct[name] = Proc(name, dct)

    def proc(self, name):
        return self.dct[name]

    def killall(self):
        for process in self.dct.items():
            try:
                process[1].kill()

            except AttributeError:
                pass


def wsThread():
    global proc_status
    while True:
        proc_status = getStatusAsJson()

        time.sleep(3)


procs = Procs()


def listConfigFiles() -> list:
    configfiles = []

    for root, _, files in os.walk(app.config["configdir"]):
        for file in files:
            if file.endswith("~") or file.endswith("#"):
                continue

            configfiles.append(root.rstrip("/") + "/" + file)

    return configfiles


def fname(path) -> str:
    return path.split("/")[-1].replace(".toml", "")


def changed() -> list:
    global LASTUPDATE

    changedfiles = []

    for file in listConfigFiles():
        if datetime.fromtimestamp(os.path.getmtime(file)) > LASTUPDATE:
            changedfiles.append(fname(file))
            
    LASTUPDATE = datetime.now()

    return changedfiles


def loadConfig() -> dict:
    config = {}

    for filename in listConfigFiles():
        config[fname(filename)] = toml.load(filename)

    return config


def saveConfig(newconfig):
    for key in newconfig.keys():
        with open(configdir + "/" + key + ".toml", "w") as configfile:
            toml.dump(newconfig[key], configfile)


def startProcs():
    global cfg

    cfg = loadConfig()
    chg = changed()

    for proc in cfg.keys():
        if proc in chg:
            print(f"Loading {proc}")
            if "start" not in proc:
                procs.start(proc, cfg[proc])
            else:
                if proc["start"]:
                    procs.start(proc, cfg[proc])


def start():
    if not os.path.exists(app.config["configdir"]):
        os.mkdir(app.config["configdir"])

    if os.path.exists(app.config["configfile"]):
        with open(app.config["configfile"], "r") as configfile:
            saveConfig(toml.load(configfile))

        os.remove(app.config["configfile"])

    threading.Thread(target=wsThread, daemon=True).start()

    startProcs()


def memUsage():
    outlines = subprocess.check_output("free -m".split()).decode().split("\n")

    mem = outlines[1]

    while "  " in mem:
        mem = mem.replace("  ", " ")

    memvals = mem.split()

    swap = outlines[2]

    while "  " in swap:
        swap = swap.replace("  ", " ")

    swapvals = swap.split()

    return [
        int(val)
        for val in [
            memvals[2],
            memvals[4],
            memvals[5],
            memvals[6],
            swapvals[2],
            swapvals[3],
        ]
    ]


def cpuUsage():
    usage = (
        subprocess.check_output(
            ["bash", "-c", "top -b -n1 | grep \"Cpu(s)\" | awk '{print $2+$4}'"]
        )
        .decode()
        .rstrip("\n")
    )

    return [float(usage), 100 - float(usage)]


@app.route("/stats")
def statusAPI():
    return json.dumps([memUsage(), cpuUsage()])


@app.route("/kill/<proc>")
def killProc(proc):
    if proc in procs.dct.keys():
        procs.proc(proc).kill()

    return redirect("/proc/" + proc)


@app.route("/restart/<proc>")
def restartProc(proc):
    if proc in procs.dct.keys():
        procs.proc(proc).kill()
        procs.start(proc, cfg[proc])

    return redirect("/proc/" + proc)


@app.route("/start/<proc>")
def startProc(proc):
    procs.start(proc, cfg[proc])

    return redirect("/proc/" + proc)


@app.route("/pause/<proc>")
def pauseProc(proc):
    procs.proc(proc).paused = True
    os.kill(procs.proc(proc).process.pid, signal.SIGSTOP)

    return redirect("/proc/" + proc)


@app.route("/unpause/<proc>")
def unpauseProc(proc):
    procs.proc(proc).paused = False
    os.kill(procs.proc(proc).process.pid, signal.SIGCONT)

    return redirect("/proc/" + proc)


from ansi2html import Ansi2HTMLConverter

conv = Ansi2HTMLConverter()


@app.route("/out/<proc>")
def statTest(proc):
    return conv.convert(str(procs.proc(proc).out))


@app.route("/reload")
def reloadAll():
    start()

    return redirect("/list")


def getStatusAsJson():
    if len(procs.dct.keys()) == 0:
        return json.dumps(
            {
                "running": "0",
                "paused": "0",
                "killed": "100",
                "done": "0",
            }
        )

    running = 0
    paused = 0
    crashed = 0
    done = 0

    for proc in procs.dct.keys():
        prc = procs.proc(proc)
        if not prc.running and not prc.paused and prc.returncode == 0:
            done += 1

        elif not prc.running:
            crashed += 1

        elif prc.running and not prc.paused:
            running += 1

        elif prc.paused:
            paused += 1

    tprocs = len(procs.dct.keys())

    runningpercent = running / tprocs
    pausedpercent = paused / tprocs
    crashedpercent = crashed / tprocs
    donepercent = done / tprocs

    return json.dumps(
        {
            "running": f"{round(runningpercent*100)}",
            "paused": f"{round(pausedpercent*100)}",
            "killed": f"{round(crashedpercent*100)}",
            "done": f"{round(donepercent*100)}",
        }
    )


@sock.route("/ws/status")
def ws_status(ws):
    while True:
        ws.send(proc_status)

        time.sleep(3)


@app.route("/")
def home():
    return render_template("main.html", mem=str(memUsage()), cpu=str(cpuUsage()))


@app.route("/list")
def listProcs():
    return render_template(
        "list.html",
        procs=[
            {
                "running": procs.dct[i].running,
                "process": i,
                "paused": procs.dct[i].paused,
                "returncode": procs.dct[i].returncode,
            }
            for i in procs.dct
        ],
        str=str,
    )


@app.route("/proc/<proc>")
def procShow(proc):
    return render_template(
        "proc.html",
        proc=proc,
        procdata=procs.proc(proc).dct,
        running=procs.proc(proc).running,
        paused=procs.proc(proc).paused,
        returncode=procs.proc(proc).returncode,
    )


def cleanup_processes(signal, frame):
    procs.killall()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup_processes)

proc_status = getStatusAsJson()


@app.route("/source/<path:filename>")
def returnSourceFile(filename):
    return send_from_directory(app.config["staticdir"], filename)


if __name__ == "__main__":
    start()
    app.run("0.0.0.0", port=4057, debug="--debug" in sys.argv)
