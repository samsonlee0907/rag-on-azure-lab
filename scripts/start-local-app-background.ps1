param(
    [int]$Port = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "run-local-app.ps1"
$stdoutSuffix = if ($Port -eq 8000) { "" } else { "-$Port" }
$stdout = Join-Path $workspace "server-live$stdoutSuffix.stdout.log"
$stderr = Join-Path $workspace "server-live$stdoutSuffix.stderr.log"

function Resolve-ShellPath {
    $pwshCommand = Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pwshCommand) {
        return $pwshCommand.Source
    }

    $powershellCommand = Get-Command powershell -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($powershellCommand) {
        return $powershellCommand.Source
    }

    throw "PowerShell was not found on PATH. Install PowerShell and make sure 'pwsh' or 'powershell' is available."
}

$pwsh = Resolve-ShellPath
$port = $Port

$deadline = (Get-Date).AddSeconds(15)
while ($true) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) {
        break
    }
    if ((Get-Date) -ge $deadline) {
        throw "Port $port is still in use by process $($listener.OwningProcess)."
    }
    Start-Sleep -Milliseconds 500
}

$process = Start-Process `
    -FilePath $pwsh `
    -ArgumentList "-ExecutionPolicy", "Bypass", "-File", $launcher, "-Port", $port `
    -WorkingDirectory $workspace `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$process.Id
