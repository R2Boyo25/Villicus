from flask import *
import toml
import json
import os
import subprocess
import logging
import click
from fcntl import fcntl, F_GETFL, F_SETFL
from os import O_NONBLOCK, read
import signal
from datetime import datetime

app = Flask('ProgramManager')
configfile = os.path.expanduser("~/.config/programmanager.toml")
configdir = os.path.expanduser("~/.config/programmanager/")

#### Disable Logging ####

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


def secho(text, file=None, nl=None, err=None, color=None, **styles):
    pass


def echo(text, file=None, nl=None, err=None, color=None, **styles):
    pass


click.echo = echo
click.secho = secho

#### Disable Logging ####

LASTUPDATE = datetime(year=1, month=1, day=1)

cfg = {}


class Proc:
    def __init__(self, name, dct):
        self.name = name
        self.dct = dct
        self.process = None
        self.env = os.environ.copy()
        self.paused = False
        if "start" in self.dct:
            if self.dct["start"]:
                self.start()
        else:
            self.start()
        self.curout = []

    def start(self):
        proc = self.dct
        if "command" in proc:
            command = proc["command"]  # .split()
        else:
            return

        workdir = proc["workdir"] if "workdir" in proc else os.getcwd()

        if "env" in proc:
            for var in proc['env'].keys():
                self.env[var] = proc['env'][var]

        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, cwd=workdir, env=self.env, shell=True, preexec_fn=os.setsid)

        flags = fcntl(self.process.stdout, F_GETFL)
        fcntl(self.process.stdout, F_SETFL, flags | O_NONBLOCK)

    def kill(self):
        os.killpg(self.process.pid, signal.SIGTERM)

    @property
    def out(self):
        o = ""
        if self.running:
            while True:
                try:
                    o += read(self.process.stdout.fileno(), 4096).decode()
                except OSError:
                    break
        else:
            o += self.process.stdout.read().decode()

        if o.strip().strip("\n") != "":
            self.curout.append(o.strip("\n"))

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
        rt = self.process.returncode
        return rt if rt else 0


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


procs = Procs()


def listConfigFiles() -> list:
    c = []

    for root, dirs, files in os.walk(configdir):
        for file in files:
            c.append(root.rstrip("/") + "/" + file)

    return c


def fname(path) -> str:
    return path.split("/")[-1].replace(".toml", "")


def changed() -> list:
    global LASTUPDATE

    c = []

    for file in listConfigFiles():
        if datetime.fromtimestamp(os.path.getmtime(file)) > LASTUPDATE:
            c.append(fname(file))
    LASTUPDATE = datetime.now()

    return c


def loadConfig() -> dict:
    d = {}

    for f in listConfigFiles():
        d[fname(f)] = toml.load(f)

    return d


def saveConfig(newconfig):
    for k in newconfig.keys():
        with open(configdir + "/" + k + ".toml", "w") as pf:
            toml.dump(newconfig[k], pf)


def startProcs():
    global cfg
    global procs

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
    global procs

    if not os.path.exists(configdir):
        os.mkdir(configdir)

    if os.path.exists(configfile):
        with open(configfile, "r") as cf:
            a = toml.load(cf)

        saveConfig(a)

        os.remove(configfile)

    startProcs()


def memUsage():
    aa = subprocess.check_output("free -m".split()).decode().split("\n")

    a = aa[1]

    while "  " in a:
        a = a.replace("  ", " ")

    ae = a.split()

    af = aa[2]

    while "  " in a:
        af = af.replace("  ", " ")

    af = af.split()

    return [int(e) for e in [ae[2], ae[4], ae[5], ae[6], af[2], af[3]]]


def cpuUsage():
    a = subprocess.check_output(
        ["bash", "-c", "top -b -n1 | grep \"Cpu(s)\" | awk '{print $2+$4}'"]).decode().rstrip("\n")

    return [float(a), 100 - float(a)]


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
    global cfg
    if proc in procs.dct.keys():
        procs.proc(proc).kill()
        procs.start(proc, cfg[proc])

    return redirect("/proc/" + proc)


@app.route("/start/<proc>")
def startProc(proc):
    global cfg
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


@app.route("/out/<proc>")
def statTest(proc):
    return str(procs.proc(proc).out).replace("\n", "<br>\n")


@app.route("/reload")
def reloadAll():
    start()

    return redirect("/list")


@app.route("/status")
def jsonStatus():
    if len(procs.dct.keys()) > 0:
        running = 0
        paused = 0
        crashed = 0
        done = 0
        for proc in procs.dct.keys():
            prc = procs.proc(proc)
            if not (prc.running and not prc.paused) and prc.returncode == 0:
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

        return json.dumps({
            "running": f"{round(runningpercent*100)}%",
            "paused": f"{round(pausedpercent*100)}%",
            "killed": f"{round(crashedpercent*100)}%",
            "done": f"{round(donepercent*100)}%",
        })
    else:
        return json.dumps({
            "running": "0%",
            "paused": "0%",
            "killed": "100%",
            "done": "0%",
        })


@app.route('/')
def home():
    return render_template('main.html', mem=str(memUsage()), cpu=str(cpuUsage()))


@app.route("/list")
def listProcs():
    return render_template("list.html", procs=[{"running": procs.dct[i].running, "process":i, "paused":procs.dct[i].paused, "returncode":procs.dct[i].returncode} for i in procs.dct], str=str)


@app.route("/proc/<proc>")
def procShow(proc):
    return render_template("proc.html", proc=proc, procdata=procs.proc(proc).dct, running=procs.proc(proc).running, paused=procs.proc(proc).paused, returncode=procs.proc(proc).returncode)


@app.route('/source/<path:filename>')
def returnSourceFile(filename):
    return send_from_directory('source', filename)


if __name__ == '__main__':
    start()
    app.run(host='0.0.0.0', port=4057)
