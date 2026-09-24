#Requires -Version 7.4
[CmdletBinding()]
param(
    [switch]$Desktop,
    [switch]$Cache,
    [switch]$NoBrowser,
    [ValidateRange(1, 65535)][int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
if ($Cache) {
    if ($Desktop) { throw 'Use -Cache separately from -Desktop.' }
    & (Join-Path $PSScriptRoot 'build-probe.ps1') -Cache
    return
}
$logDirectory = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$probeFile = Join-Path $logDirectory 'model-probe.jsonl'

if ($Desktop) {
    if (Get-Process -Name ChatGPT -ErrorAction SilentlyContinue) {
        throw 'Close Codex completely, then run codex-monitor -Desktop again. Running tasks will not be interrupted automatically.'
    }
    $backend = & (Join-Path $PSScriptRoot 'build-probe.ps1')
    $currentDesktop = & (Join-Path $PSScriptRoot 'build-probe.ps1') -Inspect
    if ($currentDesktop.Package -ne $backend.Package -or $currentDesktop.Version -ne $backend.Version) {
        throw 'Codex updated during probe preparation. Run codex-monitor -Desktop again to match the new version.'
    }
    $package = Get-AppxPackage -Name 'OpenAI.Codex' | Where-Object PackageFullName -EQ $backend.Package
    $desktopExe = Join-Path $package.InstallLocation 'app\ChatGPT.exe'
    Start-Process -FilePath $desktopExe -Environment @{
        CODEX_CLI_PATH = Join-Path $backend.BinaryDirectory 'codex.exe'
        CODEX_MODEL_PROBE_PATH = $probeFile
    }
}

$monitorArguments = @((Join-Path $PSScriptRoot 'monitor.py'), '--port', $Port, '--probe-file', $probeFile)
if ($NoBrowser) { $monitorArguments += '--no-browser' }
& python @monitorArguments
exit $LASTEXITCODE
