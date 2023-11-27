"""
The main file for Villicus.
"""


from fcntl import fcntl, F_GETFL, F_SETFL
from os import O_NONBLOCK
from datetime import datetime
from typing import Any
from pathlib import Path

import time
import json
import os
import subprocess
import logging
import sys
import signal
import threading

import toml

from flask import Flask, redirect, render_template, send_from_directory
from werkzeug import Response
from flask_sock import Sock  # type: ignore
from ansi2html import Ansi2HTMLConverter

conv = Ansi2HTMLConverter()
app = Flask("Villicus")
sock = Sock(app)

app.config.update(
    staticdir="static",
    configfile=os.path.expanduser("~/.config/villicus.toml"),
    configdir=os.path.expanduser("~/.config/villicus/"),
)

###> Disable Logging >###

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

###< Disable Logging <###

websockets: list[Sock] = []


class Proc:
    """A class representing a single process managed by Villicus."""

    def __init__(self, name: str, dct: dict[str, Any]) -> None:
        self.name = name
        self.dct = dct
        self.process: subprocess.Popen[bytes] | None = None
        self.env = os.environ.copy()
        self.paused = False
        self.curout: list[str] = []

        if "start" not in self.dct:
            self.start()
            return

        if self.dct["start"]:
            self.start()

    def start(self) -> None:
        """Starts the process"""

        proc = self.dct

        if "command" not in proc:
            return

        command = proc["command"]
        workdir = proc["workdir"] if "workdir" in proc else os.getcwd()

        if "env" in proc:
            for var in proc["env"]:
                self.env[var] = proc["env"][var]

        self.process = subprocess.Popen(  # pylint: disable=R1732, W1509
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

        flags = fcntl(self.process.stdout, F_GETFL)  # type: ignore[arg-type]
        fcntl(self.process.stdout, F_SETFL, flags | O_NONBLOCK)  # type: ignore[arg-type]

    def kill(self) -> None:
        """Kills the process, if it is running."""

        if not self.process:
            return

        try:
            os.killpg(self.process.pid, signal.SIGTERM)

        except ProcessLookupError:
            pass

    @property
    def out(self) -> str:
        """The combined stdout and stderr of the process."""

        if self.process is None:
            return ""

        while True:
            if not self.process.stdout:
                break

            tmp: bytes | None = self.process.stdout.readline()

            if not tmp:
                break

            self.curout.append(tmp.decode().strip("\n"))

            if not self.process.poll() and not tmp:
                break

        return "\n".join(self.curout)

    @property
    def running(self) -> bool:
        """Whether the process is running (i.e. not exited)"""

        if not self.paused:
            if self.process is None:
                return False

            return self.process.poll() is None

        return True

    @property
    def returncode(self) -> int:
        """The current return code for the process, or -111 if
        it was never started or is still running."""

        if self.process is None:
            return -111

        returncode: int = self.process.returncode
        return returncode if returncode is not None else -111


class Procs:
    """A wrapper class to handle managing all of the processes."""

    def __init__(self) -> None:
        self.dct: dict[str, Proc] = {}

    def start(self, name: str, dct: dict[str, Any] | None=None) -> None:
        """Starts and registers a process."""

        if dct is None:
            return

        if name in self.dct:
            if self.dct[name].running:
                self.dct[name].kill()

        self.dct[name] = Proc(name, dct)

    def __getitem__(self, name: str) -> Proc:
        """Gets a process."""

        return self.dct[name]

    def killall(self) -> None:
        """Kills all running processes."""

        for process in self.dct.items():
            try:
                process[1].kill()

            except AttributeError:
                pass


class State:
    """Global state for Villicus."""

    def __init__(self) -> None:
        self.process_statuses = self.get_process_statuses()
        self.config: dict[str, dict[str, Any]] = {}
        self.last_reloaded = datetime(year=1, month=1, day=1)

    def update_thread(self) -> None:
        """Manages updating the process status every 3 seconds."""

        while True:
            self.process_statuses = self.get_process_statuses()
            time.sleep(3)

    def get_process_statuses(self) -> str:
        """Gets the process statuses."""

        if len(procs.dct) == 0:
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

        for proc in procs.dct:
            prc = procs[proc]
            if not prc.running and not prc.paused and prc.returncode == 0:
                done += 1

            elif not prc.running:
                crashed += 1

            elif prc.running and not prc.paused:
                running += 1

            elif prc.paused:
                paused += 1

        tprocs = len(procs.dct)

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


procs = Procs()
state = State()


@sock.route("/ws/status")  # type: ignore[misc]
def ws_status(ws: Sock) -> None:
    """Sends the current process status over the websocket every 3 seconds."""

    while True:
        ws.send(state.process_statuses)

        time.sleep(3)


def get_config_files() -> list[str]:
    """Gets a list of all of the config files."""

    configfiles = []

    for root, _, files in os.walk(app.config["configdir"]):
        for file in files:
            if file.endswith("~") or file.endswith("#"):
                continue

            configfiles.append(root.rstrip("/") + "/" + file)

    return configfiles


def changed_config_files() -> list[str]:
    """Gets a list of all of the config files that have been modified since
    the last call to this function."""

    changedfiles = []

    for file in get_config_files():
        if datetime.fromtimestamp(os.path.getmtime(file)) > state.last_reloaded:
            changedfiles.append(Path(file).stem)

    state.last_reloaded = datetime.now()

    return changedfiles


def load_configuration() -> dict[str, dict[str, Any]]:
    """Loads all of the config files."""

    config = {}

    for filename in get_config_files():
        config[Path(filename).stem] = toml.load(filename)

    return config


def save_split_configuration(newconfig: dict[str, dict[str, Any]]) -> None:
    """Saves each key-value pair as a separate file."""

    for key in newconfig:
        with open(
            f"{app.config['configdir']}/{key}.toml", "w", encoding="utf-8"
        ) as configfile:
            toml.dump(newconfig[key], configfile)


def start_processes() -> None:
    """Loads the configuration and (re)starts the processes that have been changed."""

    state.config = load_configuration()
    chg = changed_config_files()

    for proc, val in state.config.items():
        if proc in chg:
            print(f"Loading {proc}")

            if val.get("start", True):
                procs.start(proc, val)


def start() -> None:
    """Sets up the app by loading config, starting threads, and starting processes."""

    if not os.path.exists(app.config["configdir"]):
        os.mkdir(app.config["configdir"])

    if os.path.exists(app.config["configfile"]):
        with open(app.config["configfile"], "r", encoding="utf-8") as configfile:
            save_split_configuration(toml.load(configfile))

        os.remove(app.config["configfile"])

    threading.Thread(target=state.update_thread, daemon=True).start()

    start_processes()


def get_memory_usage() -> list[int]:
    """Gets the memory usage values in MB:
    used, shared, buff/cache, available, swap used, swap free

    TODO: switch to dataclass"""

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


def get_cpu_usage() -> list[float]:
    """Gets the cpu usage in percentage: [used, not used]."""

    usage = (
        subprocess.check_output(
            ["bash", "-c", "top -b -n1 | grep \"Cpu(s)\" | awk '{print $2+$4}'"]
        )
        .decode()
        .rstrip("\n")
    )

    return [float(usage), 100 - float(usage)]


@app.route("/stats")
def get_status() -> str:
    """Gets the memory and cpu usage."""

    return json.dumps([get_memory_usage(), get_cpu_usage()])


@app.route("/kill/<proc>")
def kill_process(proc: str) -> Response:
    """Kills the process."""

    if proc in procs.dct:
        procs[proc].kill()

    return redirect("/proc/" + proc)


@app.route("/restart/<proc>")
def restart_process(proc: str) -> Response:
    """Restarts the process."""

    if proc in procs.dct:
        procs[proc].kill()
        procs.start(proc, state.config[proc])

    return redirect("/proc/" + proc)


@app.route("/start/<proc>")
def start_process(proc: str) -> Response:
    """Starts the process."""

    procs.start(proc, state.config[proc])

    return redirect("/proc/" + proc)


@app.route("/pause/<proc>")
def pause_process(proc: str) -> Response:
    """Pauses the process."""

    process = procs[proc]
    process.paused = True

    if process.process is not None:
        os.kill(process.process.pid, signal.SIGSTOP)

    return redirect("/proc/" + proc)


@app.route("/unpause/<proc>")
def unpause_process(proc: str) -> Response:
    """Unpauses the process."""

    process = procs[proc]
    process.paused = False

    if process.process is not None:
        os.kill(process.process.pid, signal.SIGCONT)

    return redirect("/proc/" + proc)


@app.route("/out/<proc>")
def get_process_output(proc: str) -> str:
    """Gets the full output of the process."""

    return conv.convert(str(procs[proc].out))


@app.route("/reload")
def reload_processes() -> Response:
    """Reloads all of the processes."""

    start()

    return redirect("/list")


@app.route("/")
def home() -> str:
    """Displays the homepage."""

    return render_template(
        "main.html", mem=str(get_memory_usage()), cpu=str(get_cpu_usage())
    )


@app.route("/list")
def process_list() -> str:
    """Displays the list of processes."""

    return render_template(
        "list.html",
        procs=[
            {
                "running": proc.running,
                "process": name,
                "paused": proc.paused,
                "returncode": proc.returncode,
            }
            for name, proc in procs.dct.items()
        ],
        str=str,
    )


@app.route("/proc/<proc>")
def process_details(proc: str) -> str:
    """Displays the detailed view for a process."""

    process = procs[proc]

    return render_template(
        "proc.html",
        proc=proc,
        procdata=process.dct,
        running=process.running,
        paused=process.paused,
        returncode=process.returncode,
    )


def cleanup_processes(_signal: Any, _frame: Any) -> None:
    """Kills all of the processess and exits."""

    procs.killall()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup_processes)


@app.route("/source/<path:filename>")
def return_source_file(filename: str) -> Response:
    """Returns a static file from the staticdir."""

    return send_from_directory(app.config["staticdir"], filename)


if __name__ == "__main__":
    start()
    app.run("0.0.0.0", port=4057, debug="--debug" in sys.argv)
