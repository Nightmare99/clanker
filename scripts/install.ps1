# Clanker Installation Script for Windows
# Usage:
#   irm https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.ps1 | iex
#   $env:CLANKER_VERSION = "v0.8.5"; irm https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.ps1))) -Version v0.8.5
#
# An optional version (e.g. "v0.8.5" or "0.8.5") installs that release instead
# of the latest one, via the -Version parameter or the CLANKER_VERSION env var.
# `iex` pipelines can't take parameters directly, so use the CLANKER_VERSION
# env var when piping, or the scriptblock form above for -Version.

param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

$Repo = "Nightmare99/clanker"
$BinaryName = "clanker.exe"
$InstallDir = if ($env:CLANKER_INSTALL_DIR) { $env:CLANKER_INSTALL_DIR } else { "$env:LOCALAPPDATA\clanker\bin" }
$RequestedVersion = if ($Version) { $Version } elseif ($env:CLANKER_VERSION) { $env:CLANKER_VERSION } else { $null }

function Write-Info    { param($Msg) Write-Host "  ▸ $Msg" -ForegroundColor Cyan }
function Write-Ok      { param($Msg) Write-Host "  ✓ $Msg" -ForegroundColor Green }
function Write-Warn    { param($Msg) Write-Host "  ! $Msg" -ForegroundColor Yellow }
function Write-Err     { param($Msg) Write-Host "  ✗ $Msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  ⚙  Clanker Installer" -ForegroundColor Cyan
Write-Host "  ─────────────────────" -ForegroundColor DarkGray
Write-Host ""

# Detect architecture
$Arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { Write-Err "32-bit Windows is not supported." }
Write-Info "Platform: windows-$Arch"

# Resolve the version to install
if ($RequestedVersion) {
    $Version = if ($RequestedVersion -match '^v') { $RequestedVersion } else { "v$RequestedVersion" }
    Write-Info "Requested version: $Version"
    try {
        Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/$Version" -UseBasicParsing | Out-Null
    } catch {
        Write-Err "Release $Version not found. Check available releases at https://github.com/$Repo/releases"
    }
    $Pinned = $true
} else {
    Write-Info "Fetching latest release..."
    try {
        $Release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing
        $Version = $Release.tag_name
    } catch {
        Write-Err "Could not determine latest version. Check your internet connection."
    }
    $Pinned = $false
}
Write-Info "Version: $Version"

# Check for existing installation
$ExistingBinary = Join-Path $InstallDir $BinaryName
if (Test-Path $ExistingBinary) {
    try {
        $VersionOutput = & $ExistingBinary --version 2>&1
        $InstalledVersion = if ($VersionOutput -match 'v?(\d+\.\d+\.\d+)') { $Matches[1] } else { $null }
    } catch {
        $InstalledVersion = $null
    }

    if ($InstalledVersion) {
        $TargetClean = $Version -replace '^v', ''
        if ($InstalledVersion -eq $TargetClean) {
            Write-Host ""
            Write-Ok "Clanker $Version is already installed."
            Write-Host ""
            exit 0
        }
        Write-Host ""
        Write-Info "Installed: v$InstalledVersion"
        Write-Info "$(if ($Pinned) { 'Target:   ' } else { 'Latest:   ' })$Version"
        Write-Host ""
    }
}

# Download
$Filename = "clanker-windows-amd64.zip"
$DownloadUrl = "https://github.com/$Repo/releases/download/$Version/$Filename"
Write-Info "Downloading $Filename..."

$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) "clanker-install-$(Get-Random)"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
$ArchivePath = Join-Path $TempDir $Filename

try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath -UseBasicParsing
} catch {
    Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
    Write-Err "Download failed: $DownloadUrl"
}

# Extract and install
try {
    Expand-Archive -Path $ArchivePath -DestinationPath $TempDir -Force
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Copy-Item -Path (Join-Path $TempDir $BinaryName) -Destination (Join-Path $InstallDir $BinaryName) -Force
} finally {
    Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
}
Write-Ok "Installed to $InstallDir\$BinaryName"

# Check if install dir is in PATH
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$InstallDir*") {
    Write-Host ""
    Write-Warn "$InstallDir is not in your PATH."
    Write-Host ""
    Write-Host "  Run this to add it:" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"$InstallDir;`$env:Path`", 'User')" -ForegroundColor DarkGray
    Write-Host ""

    $AddToPath = Read-Host "  Add to PATH now? [Y/n]"
    if ($AddToPath -ne 'n' -and $AddToPath -ne 'N') {
        [Environment]::SetEnvironmentVariable("Path", "$InstallDir;$UserPath", "User")
        $env:Path = "$InstallDir;$env:Path"
        Write-Ok "Added to PATH."
    }
}

Write-Host ""
Write-Host "  Done!" -ForegroundColor Green -NoNewline
Write-Host " Run " -NoNewline
Write-Host "clanker" -ForegroundColor Cyan -NoNewline
Write-Host " to get started."
Write-Host ""
