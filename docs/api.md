# API

# `/stats`
The two following sections are in the order they will be returned from this endpoint.
## Memory
A JSON list of integers (MB): 
- Used memory
- Shared Memory
- Disk Cache
- Available Memory
- Used Swap
- Free Swap
## CPU
A JSON list of integers (%):
- CPU Usage
- 100 - CPU Usage

# `/kill/<proc>`
Kills `proc`

# `/restart/<proc>`
Restarts `proc`

# `/pause/<proc>`
Pauses `proc` - [SIGSTOP](https://en.wikipedia.org/wiki/Signal_(IPC)#SIGSTOP)

# `/unpause/<proc>`
Unpauses `proc` - [SIGCONT](https://en.wikipedia.org/wiki/Signal_(IPC)#SIGCONT)

# `/out/<proc>`
Returns the STDOUT & STDERR for `proc` with `\n` replaced with `<br>\n`

# `/reload`
Reloads the configuration file and restarts any changed processes.

# `/status`
Returns a JSON dictionary with strings (`000.00%`) for the percentage of processes in that state.

## `running`
Processes that are currently running.

## `paused`
Processes that have been [paused](#pauseproc)

## `killed`
Processes with return codes other than `0` (So they crashed or were killed.)

## `done`
Processes with a return code of `0` (So they exited normally.)