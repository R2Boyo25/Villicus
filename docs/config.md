# Config
Process configuration files are stored in `$HOME/.config/programmanager`.
They use [TOML syntax](https://toml.io/en/).
They can be named anything as long as it ends with `.toml`. The text before `.toml` will be the process name.

## `command`
The command to run for the process.

## `workdir` (optional; defaults to `progman`'s working directory)
The directory to run the process in.

## `start` (optional)
Whether to start a command when `progman` is started. (Or when the configuration is reloaded for the process.)

## `env` (optional)
`env` is a table where the key's names are environment variable's names and their values are assigned to the environment variables.
```toml
[env]
var = "value"
var2 = "value2"
```

# Basic Example
```toml
command = "pwd"
workingdirectory = "/etc/"
```

# Basic Example w/ `env`
```toml
command = 'echo "$GREETING"'

[env]
GREETING = "Hallo!"
```