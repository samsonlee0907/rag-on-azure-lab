param(
    [int]$Port = 8000,
    [string]$EnvFile = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$envFilePath = if ($EnvFile) {
    if ([System.IO.Path]::IsPathRooted($EnvFile)) {
        $EnvFile
    }
    else {
        Join-Path $workspace $EnvFile
    }
}
else {
    Join-Path $workspace ".env"
}

function Resolve-PythonPath {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pythonCommand) {
        return [pscustomobject]@{
            Path = $pythonCommand.Source
            PrefixArgs = @()
        }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pyCommand) {
        return [pscustomobject]@{
            Path = $pyCommand.Source
            PrefixArgs = @("-3")
        }
    }

    throw "Python was not found on PATH. Install Python 3.11+ and make sure 'python' or 'py' is available."
}

$python = Resolve-PythonPath

if (-not (Test-Path $envFilePath)) {
    throw ".env not found at $envFilePath"
}

Get-Content $envFilePath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }
    $pair = $line -split "=", 2
    if ($pair.Count -eq 2) {
        [System.Environment]::SetEnvironmentVariable($pair[0], $pair[1], "Process")
    }
}

Set-Location $workspace
& $python.Path @($python.PrefixArgs + @("-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", $Port))
