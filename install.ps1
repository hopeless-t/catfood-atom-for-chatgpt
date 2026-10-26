$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 "$ScriptDir\install.py" @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$ScriptDir\install.py" @args
} else {
    throw "Python 3 was not found. Install Python 3 and run this script again."
}
exit $LASTEXITCODE
