# Program Manager

Configuration files are stored in `~/.config/programmanager`
Each program is a separate toml config file: `program_name.toml`
The web interface it at port 4057.

# Config Options

```toml
# The command to run.
command = "command --to run"

# directory for command to be run from.
workdir = "/path/to/working/directory"

# Whether or not to start the program
# when the program manager is started
# (so you have to start it manually)
start = true or false

# environment variables
[env]
variablename1 = "variablevalue 1"
variablename2 = "variable value 2"
```