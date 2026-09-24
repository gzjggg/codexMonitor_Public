[CmdletBinding()]
param([switch]$Inspect, [switch]$Cache)

$ErrorActionPreference = 'Stop'

function Get-ProbeVersion([string]$Binary, [string]$ExpectedVersion) {
    $reported = & $Binary --version
    if ($LASTEXITCODE -ne 0 -or "$reported" -ne "codex-cli $ExpectedVersion") {
        throw 'Probe backend version does not match the desktop backend.'
    }
    return "$reported".Substring('codex-cli '.Length)
}

function Test-PathInside([string]$Path, [string]$Directory) {
    $candidate = [IO.Path]::GetFullPath($Path)
    $parent = [IO.Path]::GetFullPath($Directory).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $candidate.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)
}

function Remove-GeneratedDirectory([string]$Path, [string]$Parent) {
    if (-not (Test-PathInside $Path $Parent)) { throw "Refusing to remove a directory outside $Parent`: $Path" }
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

function Assert-NotRunning([string[]]$Directories) {
    if ($Directories.Count -eq 0) { return }
    $active = Get-CimInstance Win32_Process | Where-Object {
        $executablePath = $_.ExecutablePath
        $executablePath -and @($Directories | Where-Object { Test-PathInside $executablePath $_ }).Count -gt 0
    } | Select-Object -First 1
    if ($active) { throw "Probe backend is still running from $($active.ExecutablePath). Exit Codex before replacing its cache." }
}

function Remove-OldProbeCaches([string]$ProbeRoot, [string]$Keep) {
    $remove = @()
    if (Test-Path -LiteralPath $ProbeRoot) {
        foreach ($versionDirectory in Get-ChildItem -LiteralPath $ProbeRoot -Directory) {
            if ($Keep -and (Test-PathInside $Keep $versionDirectory.FullName)) {
                $remove += @(Get-ChildItem -LiteralPath $versionDirectory.FullName -Directory | Where-Object {
                    -not $_.FullName.Equals($Keep, [StringComparison]::OrdinalIgnoreCase)
                } | ForEach-Object FullName)
            }
            else { $remove += $versionDirectory.FullName }
        }
    }
    Assert-NotRunning $remove
    foreach ($directory in $remove) { Remove-GeneratedDirectory $directory $ProbeRoot }
}

function Remove-CompilationCache([string]$Repository, [string]$OutputRoot, [switch]$Force) {
    $settingsFile = Join-Path (Split-Path $OutputRoot -Parent) '.monitor-settings.json'
    if (-not $Force -and (Test-Path -LiteralPath $settingsFile)) {
        $settings = Get-Content -LiteralPath $settingsFile -Raw | ConvertFrom-Json
        if ($settings.keepBuildCache -eq $true) { return }
    }
    $compileDirectories = @((Join-Path $OutputRoot 'target'), (Join-Path $Repository 'codex-rs\target'))
    Assert-NotRunning $compileDirectories
    foreach ($directory in $compileDirectories) {
        if (Test-Path -LiteralPath $directory) {
            Write-Host "Removing compilation cache: $directory"
            Remove-GeneratedDirectory $directory (Split-Path $directory -Parent)
        }
    }
}

function Remove-OldGeneratedFiles([string]$Repository, [string]$SourceRoot, [string]$DesktopRoot, [string]$CurrentDesktop) {
    Remove-CompilationCache $Repository (Split-Path $SourceRoot -Parent)
    if (Test-Path -LiteralPath $SourceRoot) {
        $worktreeList = & git -c core.quotepath=false -C $Repository worktree list --porcelain
        if ($LASTEXITCODE -ne 0) { throw 'Could not list generated source worktrees.' }
        $registeredPaths = @($worktreeList | Where-Object { $_.StartsWith('worktree ') } | ForEach-Object {
            [IO.Path]::GetFullPath($_.Substring(9)).Replace('/', '\')
        })
        foreach ($directory in Get-ChildItem -LiteralPath $SourceRoot -Directory) {
            if (-not (Test-PathInside $directory.FullName $SourceRoot)) { throw 'Invalid generated source path.' }
            if ($registeredPaths -contains $directory.FullName) {
                & git -c core.longpaths=true -C $Repository worktree remove --force --force $directory.FullName | Out-Host
                if ($LASTEXITCODE -ne 0) { throw "Could not remove generated source worktree $($directory.FullName)." }
            }
            else {
                Remove-GeneratedDirectory $directory.FullName $SourceRoot
            }
        }
        & git -C $Repository worktree prune
        if ($LASTEXITCODE -ne 0) { throw 'Could not prune generated source worktrees.' }
    }
    if (Test-Path -LiteralPath $DesktopRoot) {
        foreach ($directory in Get-ChildItem -LiteralPath $DesktopRoot -Directory) {
            if (-not $directory.FullName.Equals($CurrentDesktop, [StringComparison]::OrdinalIgnoreCase)) {
                Remove-GeneratedDirectory $directory.FullName $DesktopRoot
            }
        }
    }
}

if ($Cache) {
    $settingsFile = Join-Path $PSScriptRoot '.monitor-settings.json'
    $keep = $false
    if (Test-Path -LiteralPath $settingsFile) {
        $keep = (Get-Content -LiteralPath $settingsFile -Raw | ConvertFrom-Json).keepBuildCache -eq $true
    }
    $choice = $Host.UI.PromptForChoice('Build cache / 构建缓存',
        'Keep compilation caches for faster rebuilds, or remove them after successful builds? / 是否保留编译缓存？',
        @('&Keep / 保留', '&Remove / 不保留', '&Cancel / 取消'), $(if ($keep) { 0 } else { 1 }))
    if ($choice -eq 2) { return }
    @{ keepBuildCache = ($choice -eq 0) } | ConvertTo-Json | Set-Content -LiteralPath $settingsFile -Encoding utf8
    Write-Host "Build cache preference saved: keep=$($choice -eq 0)"
    if ($choice -eq 1) {
        $delete = $Host.UI.PromptForChoice('Clean now? / 立即清理？',
            'Only compilation caches are removed; runnable backends and logs are kept. Stop any build first. / 仅删除编译缓存，保留后端和日志；请先停止构建。',
            @('&Now / 立即删除', '&Later / 稍后自动清理'), 1)
        if ($delete -eq 0) {
            if (Get-Process -Name cargo,rustc -ErrorAction SilentlyContinue) { throw 'A Rust build is running. Stop it before cleaning caches.' }
            Remove-CompilationCache (Join-Path $PSScriptRoot 'upstream') (Join-Path $PSScriptRoot 'output') -Force
            Write-Host 'Compilation caches cleared / 编译缓存已清理。'
        }
    }
    return
}

$package = Get-AppxPackage -Name 'OpenAI.Codex'
if (-not $package.InstallLocation) { throw 'The installed OpenAI.Codex desktop app could not be found.' }
if (@($package).Count -ne 1) { throw 'Multiple OpenAI.Codex packages found; cannot determine which desktop backend to use.' }
# WindowsApps executables may deny direct execution; inspect an unchanged local copy.
$desktopDirectory = Join-Path $PSScriptRoot "output\desktop\$($package.PackageFullName)"
New-Item -ItemType Directory -Force -Path $desktopDirectory | Out-Null
$desktopBinary = Join-Path $desktopDirectory 'codex.exe'
Copy-Item -LiteralPath (Join-Path $package.InstallLocation 'app\resources\codex.exe') -Destination $desktopBinary -Force
$versionText = & $desktopBinary --version
if ($LASTEXITCODE -ne 0 -or "$versionText" -notmatch '^codex-cli (\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$') {
    throw "Could not identify the desktop backend version: $versionText"
}
$version = $Matches[1]
$desktopVersion = $version
if ($Inspect) {
    [pscustomobject]@{ Version = $version; Package = $package.PackageFullName }
    return
}
$patch = Join-Path $PSScriptRoot 'model-probe.patch'
$patchHash = (Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash
$probeRoot = Join-Path $PSScriptRoot 'output\probes'
$cacheDirectory = Join-Path $probeRoot "$version\$patchHash"
$binaryDirectory = Join-Path $cacheDirectory 'bin'
$readyFile = Join-Path $cacheDirectory 'ready.json'
$binaries = @('codex.exe', 'codex-code-mode-host.exe', 'codex-command-runner.exe', 'codex-windows-sandbox-setup.exe')
$missing = @($binaries | Where-Object { -not (Test-Path -LiteralPath (Join-Path $binaryDirectory $_)) })
if ((Test-Path -LiteralPath $readyFile) -and $missing.Count -eq 0) {
    $version = Get-ProbeVersion (Join-Path $binaryDirectory 'codex.exe') $desktopVersion
    Remove-OldProbeCaches $probeRoot $cacheDirectory
    Remove-OldGeneratedFiles (Join-Path $PSScriptRoot 'upstream') (Join-Path $PSScriptRoot 'output\src') (Join-Path $PSScriptRoot 'output\desktop') $desktopDirectory
    Write-Host "Using cached probe backend $version-monitor"
    Write-Host "Backend executable: $(Join-Path $binaryDirectory 'codex.exe')"
    [pscustomobject]@{ Version = $desktopVersion; ProbeVersion = $version; Package = $package.PackageFullName; BinaryDirectory = $binaryDirectory }
    return
}

Write-Host "Building probe backend $version-monitor. Preparing source and dependencies; the first build may take a long time."
$repository = Join-Path $PSScriptRoot 'upstream'
$tag = "rust-v$version"
if (-not (Test-Path -LiteralPath (Join-Path $repository '.git'))) {
    & git -c core.longpaths=true clone --depth 1 --branch $tag https://github.com/openai/codex.git $repository | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Official source $tag is unavailable. No older backend will be launched." }
}
& git -C $repository rev-parse --verify --quiet "refs/tags/$tag" | Out-Null
if ($LASTEXITCODE -ne 0) {
    & git -C $repository fetch --depth 1 https://github.com/openai/codex.git "refs/tags/${tag}:refs/tags/${tag}" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Official source $tag is unavailable. No older backend will be launched." }
}
$source = Join-Path $PSScriptRoot "output\src\$version-$($patchHash.Substring(0, 12))"
if (-not (Test-Path -LiteralPath $source)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $source -Parent) | Out-Null
    & git -c core.longpaths=true -C $repository worktree add --detach $source "refs/tags/$tag" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare source $tag." }
}
& git -C $source apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -ne 0) {
    & git -C $source apply --check $patch | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "The probe patch is incompatible with $tag and must be updated. No older backend will be launched." }
    & git -C $source apply $patch | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not apply the probe patch.' }
}
Write-Host "Compiling probe backend $version-monitor..."
$savedEnvironment = @{}
foreach ($name in @('CODEX_REPO_ROOT', 'CARGO_TARGET_DIR', 'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location (Join-Path $source 'codex-rs')
try {
    $env:CODEX_REPO_ROOT = $source
    $env:CARGO_TARGET_DIR = Join-Path $PSScriptRoot 'output\target'
    $v8Environment = & python -c 'import sys,json; sys.path.insert(0,"../scripts"); from codex_package.v8 import resolve_codex_v8_cargo_env; from codex_package.targets import TARGET_SPECS; print(json.dumps(resolve_codex_v8_cargo_env(TARGET_SPECS["x86_64-pc-windows-msvc"])))'
    if ($LASTEXITCODE -ne 0) { throw 'Official V8 artifact download or checksum verification failed.' }
    $v8Environment = $v8Environment | ConvertFrom-Json
    if ($v8Environment.RUSTY_V8_ARCHIVE) {
        $env:RUSTY_V8_ARCHIVE = $v8Environment.RUSTY_V8_ARCHIVE
        $env:RUSTY_V8_SRC_BINDING_PATH = $v8Environment.RUSTY_V8_SRC_BINDING_PATH
    }
    # The release tag bumps workspace versions without regenerating Cargo.lock.
    & cargo build --profile dev-small -p codex-cli --bin codex `
        -p codex-code-mode-host --bin codex-code-mode-host `
        -p codex-windows-sandbox --bin codex-command-runner --bin codex-windows-sandbox-setup | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Probe build failed.' }
    $buildDirectory = Join-Path $env:CARGO_TARGET_DIR 'dev-small'
    $version = Get-ProbeVersion (Join-Path $buildDirectory 'codex.exe') $desktopVersion
    Assert-NotRunning @($cacheDirectory)
    New-Item -ItemType Directory -Force -Path $binaryDirectory | Out-Null
    foreach ($binary in $binaries) {
        Copy-Item -LiteralPath (Join-Path $buildDirectory $binary) -Destination (Join-Path $binaryDirectory $binary) -Force
    }
    @{ Version = $desktopVersion; ProbeVersion = $version; PatchHash = $patchHash } | ConvertTo-Json | Set-Content -LiteralPath $readyFile
}
finally {
    Pop-Location
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
}
Remove-OldProbeCaches $probeRoot $cacheDirectory
Remove-OldGeneratedFiles $repository (Join-Path $PSScriptRoot 'output\src') (Join-Path $PSScriptRoot 'output\desktop') $desktopDirectory
Write-Host "Using built probe backend $version-monitor"
Write-Host "Backend executable: $(Join-Path $binaryDirectory 'codex.exe')"
[pscustomobject]@{ Version = $desktopVersion; ProbeVersion = $version; Package = $package.PackageFullName; BinaryDirectory = $binaryDirectory }
