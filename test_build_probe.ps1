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
    $settingsFile = Join-Path $cacheTestRoot '.monitor-settings.json'
    '{"keepBuildCache":true}' | Set-Content -LiteralPath $settingsFile
    Remove-CompilationCache $repoRoot $outputRoot
    if (@($targets | Where-Object { Test-Path -LiteralPath $_ }).Count -ne 2) {
        throw 'Keep preference did not preserve compilation caches.'
    }
    '{"keepBuildCache":false}' | Set-Content -LiteralPath $settingsFile
    Remove-OldGeneratedFiles $repoRoot (Join-Path $outputRoot 'src') (Join-Path $outputRoot 'desktop') ''
    if (@($targets | Where-Object { Test-Path -LiteralPath $_ }).Count -ne 0 -or -not (Test-Path -LiteralPath $keep)) {
        throw 'Compilation cleanup must remove both target directories and preserve the runnable cache.'
    }
}
finally { Remove-GeneratedDirectory $cacheTestRoot ([IO.Path]::GetTempPath()) }

$sourceTestRoot = Join-Path ([IO.Path]::GetTempPath()) ("codex-source-check-" + [guid]::NewGuid())
try {
    $repo = Join-Path $sourceTestRoot 'upstream'
    $sources = Join-Path $sourceTestRoot 'output\src'
    & git init --quiet $repo
    & git -C $repo config core.longpaths false
    & git -C $repo -c user.name=Test -c user.email=test@example.invalid commit --quiet --allow-empty -m test
    $registered = Join-Path $sources 'registered'
    & git -C $repo worktree add --quiet --detach $registered HEAD
    $longDirectory = Join-Path $registered ('nested-' + ('x' * 130))
    New-Item -ItemType Directory -Path $longDirectory -Force | Out-Null
    $longFile = Join-Path $longDirectory (('y' * 80) + '.txt')
    Set-Content -LiteralPath $longFile -Value 'long-path build residue'
    $orphan = Join-Path $sources 'orphan'
    New-Item -ItemType Directory -Path $orphan -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $orphan 'leftover.txt') -Value 'build residue'
    Remove-OldGeneratedFiles $repo $sources (Join-Path $sourceTestRoot 'desktop') ''
    if ((Test-Path $registered) -or (Test-Path $orphan) -or -not (Test-Path (Join-Path $repo '.git'))) {
        throw 'Source cleanup must remove registered worktrees and orphan directories, preserving the repository.'
    }
}
finally { Remove-GeneratedDirectory $sourceTestRoot ([IO.Path]::GetTempPath()) }

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
