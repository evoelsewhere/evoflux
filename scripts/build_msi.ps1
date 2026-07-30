<#
.SYNOPSIS
    Build a Windows MSI installer for EvoFlux Desktop.

.DESCRIPTION
    This script builds the EvoFlux desktop application and packages it as a Windows MSI installer.
    It handles building the web frontend, Python sidecar, and the Tauri app with MSI target.

.PARAMETER SkipSidecar
    Skip building the Python sidecar bundle.

.PARAMETER SkipFrontend
    Skip building the web frontend.

.PARAMETER Dev
    Build in development mode.

.PARAMETER CertificateThumbprint
    Authenticode certificate thumbprint. Defaults to
    EVOFLUX_WINDOWS_CERTIFICATE_THUMBPRINT.

.PARAMETER AllowUnsigned
    Explicitly allow an unsigned production build for local testing.

.EXAMPLE
    .\scripts\build_msi.ps1
    .\scripts\build_msi.ps1 -SkipSidecar -SkipFrontend
    .\scripts\build_msi.ps1 -Dev
#>

param(
    [switch]$SkipSidecar,
    [switch]$SkipFrontend,
    [switch]$Dev,
    [string]$CertificateThumbprint = $env:EVOFLUX_WINDOWS_CERTIFICATE_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$AllowUnsigned
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$DesktopDir = Join-Path $RootDir "desktop"
$WebDir = Join-Path $RootDir "web"
$SidecarBundle = Join-Path $DesktopDir "sidecar-bundle"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  EvoFlux Windows MSI Builder" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# Check for cargo
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "Error: cargo not found. Install Rust from https://rustup.rs/" -ForegroundColor Red
    exit 1
}

# Check for bun
if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    Write-Host "Error: bun not found. Install bun from https://bun.sh/" -ForegroundColor Red
    exit 1
}

# Check for Python
if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command python3 -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python not found. Install Python 3.12+." -ForegroundColor Red
    exit 1
}

# Check for Tauri CLI
try {
    $tauriVersion = cargo tauri --version 2>$null
    if (-not $tauriVersion) {
        throw "Tauri CLI not installed"
    }
} catch {
    Write-Host "Installing Tauri CLI..." -ForegroundColor Yellow
    cargo install tauri-cli --version "^2.0" --locked
}

# Check for WiX Toolset
try {
    $wixVersion = wix --version 2>$null
    if (-not $wixVersion) {
        Write-Host "Warning: WiX Toolset not found. MSI build may fail." -ForegroundColor Yellow
        Write-Host "Install WiX Toolset v3+ from: https://wixtoolset.org/" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Warning: WiX Toolset not found. MSI build may fail." -ForegroundColor Yellow
    Write-Host "Install WiX Toolset v3+ from: https://wixtoolset.org/" -ForegroundColor Yellow
}

Write-Host "Prerequisites OK." -ForegroundColor Green
Write-Host ""

if ($CertificateThumbprint) {
    $CertificateThumbprint = ($CertificateThumbprint -replace "\s", "").ToUpperInvariant()
} else {
    $CertificateThumbprint = ""
}
if (-not $Dev -and -not $CertificateThumbprint -and -not $AllowUnsigned) {
    throw @"
Production Windows builds must be Authenticode-signed.
Set EVOFLUX_WINDOWS_CERTIFICATE_THUMBPRINT (or -CertificateThumbprint), or
pass -AllowUnsigned explicitly for a local non-release build.
"@
}
if ($CertificateThumbprint) {
    $certificate = Get-ChildItem Cert:\CurrentUser\My, Cert:\LocalMachine\My |
        Where-Object Thumbprint -eq $CertificateThumbprint |
        Select-Object -First 1
    if (-not $certificate) {
        throw "Signing certificate '$CertificateThumbprint' was not found in the Windows certificate stores."
    }
    Write-Host "Authenticode signing enabled: $CertificateThumbprint" -ForegroundColor Green
} elseif ($AllowUnsigned) {
    Write-Host "WARNING: producing an unsigned local build." -ForegroundColor Yellow
}

# Step 1: Build web frontend
if (-not $SkipFrontend) {
    Write-Host "Step 1/3: Building web frontend..." -ForegroundColor Yellow
    Set-Location $WebDir
    bun install --frozen-lockfile
    bun run build
    Write-Host "Web frontend built successfully." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "Step 1/3: Skipping web frontend build." -ForegroundColor Gray
}

# Step 2: Build Python sidecar
if (-not $SkipSidecar) {
    Write-Host "Step 2/3: Building Python sidecar bundle..." -ForegroundColor Yellow
    Set-Location $RootDir
    python scripts/build_sidecar.py `
        --root "$RootDir" `
        --out "$SidecarBundle" `
        --python-version 3.12
    Write-Host "Sidecar bundle built successfully." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "Step 2/3: Skipping sidecar build." -ForegroundColor Gray
}

# Step 3: Build Tauri app with MSI target
Write-Host "Step 3/3: Building Tauri app (MSI target)..." -ForegroundColor Yellow
Set-Location (Join-Path $DesktopDir "src-tauri")

if ($Dev) {
    Write-Host "Building DEV MSI..." -ForegroundColor Cyan
    cargo tauri build -c tauri.dev-bundled.conf.json --bundles msi
} else {
    Write-Host "Building PRODUCTION MSI..." -ForegroundColor Cyan
    if ($CertificateThumbprint) {
        $configOverride = @{
            bundle = @{
                windows = @{
                    certificateThumbprint = $CertificateThumbprint
                    digestAlgorithm = "sha256"
                    timestampUrl = $TimestampUrl
                    allowDowngrades = $false
                }
            }
        } | ConvertTo-Json -Depth 5 -Compress
        cargo tauri build --bundles msi --config $configOverride
    } else {
        cargo tauri build --bundles msi
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Output locations:" -ForegroundColor Cyan
Write-Host "  MSI: $DesktopDir\src-tauri\target\release\bundle\msi\"
Write-Host "  EXE: $DesktopDir\src-tauri\target\release\bundle\nsis\"
Write-Host ""

# List the MSI files if they exist
$msiDir = Join-Path $DesktopDir "src-tauri\target\release\bundle\msi"
if (Test-Path $msiDir) {
    Write-Host "Generated MSI files:" -ForegroundColor Cyan
    Get-ChildItem $msiDir | Format-Table Name, Length, LastWriteTime
}

$nsisDir = Join-Path $DesktopDir "src-tauri\target\release\bundle\nsis"
if (Test-Path $nsisDir) {
    Write-Host ""
    Write-Host "Generated NSIS installer files:" -ForegroundColor Cyan
    Get-ChildItem $nsisDir | Format-Table Name, Length, LastWriteTime
}

if ($CertificateThumbprint) {
    $signedArtifacts = @()
    if (Test-Path $msiDir) {
        $signedArtifacts += Get-ChildItem $msiDir -Filter *.msi
    }
    if (-not $signedArtifacts) {
        throw "No Windows installer artifact was found for signature verification."
    }
    foreach ($artifact in $signedArtifacts) {
        $signature = Get-AuthenticodeSignature $artifact.FullName
        if ($signature.Status -ne "Valid") {
            throw "Invalid Authenticode signature on '$($artifact.FullName)': $($signature.Status)"
        }
    }
    Write-Host "Authenticode signatures verified." -ForegroundColor Green
}
