$ErrorActionPreference = 'Stop'

$script = Join-Path $PSScriptRoot 'build-probe.ps1'
$desktop = . $script -Inspect
if (-not $desktop.Version -or -not $desktop.Package) {
    throw 'Inspect did not return the desktop backend version and package.'
}

function Report-ProbeVersion { $global:LASTEXITCODE = 0; 'codex-cli 1.2.3-alpha.4' }
if ((Get-ProbeVersion 'Report-ProbeVersion' '1.2.3-alpha.4') -ne '1.2.3-alpha.4') {
    throw 'Actual backend version was not preserved.'
}
$mismatchRejected = try { Get-ProbeVersion 'Report-ProbeVersion' '1.2.4'; $false } catch { $true }
if (-not $mismatchRejected) { throw 'A mismatched backend version was accepted.' }

$cacheTestRoot = Join-Path ([IO.Path]::GetTempPath()) ("codex-cache-check-" + [guid]::NewGuid())
try {
    $keep = Join-Path $cacheTestRoot 'new\patch'
    New-Item -ItemType Directory -Force -Path $keep, (Join-Path $cacheTestRoot 'old\patch') | Out-Null
    Remove-OldProbeCaches $cacheTestRoot $keep
    if (-not (Test-Path -LiteralPath $keep) -or (Test-Path -LiteralPath (Join-Path $cacheTestRoot 'old'))) {
        throw 'Cache cleanup did not keep only the successful version.'
    }
    $outputRoot = Join-Path $cacheTestRoot 'output'
    $repoRoot = Join-Path $cacheTestRoot 'upstream'
    $targets = @((Join-Path $outputRoot 'target'), (Join-Path $repoRoot 'codex-rs\target'))
    New-Item -ItemType Directory -Force -Path $targets | Out-Null
    Remove-OldGeneratedFiles $repoRoot (Join-Path $outputRoot 'src') (Join-Path $outputRoot 'desktop') ''
    if (@($targets | Where-Object { Test-Path -LiteralPath $_ }).Count -ne 0 -or -not (Test-Path -LiteralPath $keep)) {
        throw 'Compilation cleanup must remove both target directories and preserve the runnable cache.'
    }
}
finally { Remove-GeneratedDirectory $cacheTestRoot ([IO.Path]::GetTempPath()) }

$missingPackageFailed = & {
    function Get-AppxPackage { $null }
    try {
        & $script -Inspect
        $false
    }
    catch {
        $_.Exception.Message -eq 'The installed OpenAI.Codex desktop app could not be found.'
    }
}
if (-not $missingPackageFailed) {
    throw 'Inspect did not fail when the desktop package was missing.'
}

Write-Output "build-probe inspect checks passed: $($desktop.Version)"
