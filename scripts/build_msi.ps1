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

function Assert-NativeCommandSucceeded {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Assert-WixValidationRuntime {
    # WiX 3 executes its MSI ICE validators through the 32-bit VBScript engine.
    # Recent Windows versions make VBScript an optional capability, and Tauri
    # otherwise reduces this failure to the unhelpful "failed to run light.exe".
    $cscriptCandidates = @(
        (Join-Path $env:SystemRoot "SysWOW64\cscript.exe"),
        (Join-Path $env:SystemRoot "System32\cscript.exe")
    ) | Where-Object { Test-Path $_ } | Select-Object -Unique

    if (-not $cscriptCandidates) {
        throw "Windows Script Host was not found. WiX MSI validation requires the Windows VBScript optional capability."
    }

    $probePath = Join-Path ([System.IO.Path]::GetTempPath()) (
        "evoflux-wix-vbscript-{0}.vbs" -f [Guid]::NewGuid().ToString("N")
    )
    try {
        [System.IO.File]::WriteAllText(
            $probePath,
            "WScript.Quit 0",
            [System.Text.Encoding]::ASCII
        )

        foreach ($cscriptPath in $cscriptCandidates) {
            & $cscriptPath //E:vbscript //NoLogo $probePath *> $null
            if ($LASTEXITCODE -ne 0) {
                throw @"
The Windows VBScript engine is unavailable, so WiX light.exe cannot run MSI validation.
Install it from Settings > System > Optional features > View features > VBScript,
or run this command in an elevated PowerShell:

  Add-WindowsCapability -Online -Name VBSCRIPT~~~~0.0.1.0

Then restart PowerShell and run this build again.
"@
            }
        }
    } finally {
        Remove-Item $probePath -Force -ErrorAction SilentlyContinue
    }
}

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
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    Write-Host "Error: Python not found. Install Python 3.12+." -ForegroundColor Red
    exit 1
}

# Check for Tauri CLI
try {
    $tauriVersion = cargo tauri --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $tauriVersion) {
        throw "Tauri CLI not installed"
    }
} catch {
    Write-Host "Installing Tauri CLI..." -ForegroundColor Yellow
    cargo install tauri-cli --version "^2.0" --locked
    Assert-NativeCommandSucceeded "Tauri CLI installation"
}

# Tauri downloads its compatible WiX 3 toolset automatically. light.exe still
# depends on the Windows VBScript engine for MSI ICE validation.
Assert-WixValidationRuntime

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
    Assert-NativeCommandSucceeded "Frontend dependency installation"
    bun run build
    Assert-NativeCommandSucceeded "Frontend build"
    Write-Host "Web frontend built successfully." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "Step 1/3: Skipping web frontend build." -ForegroundColor Gray
}

# Step 2: Build Python sidecar
if (-not $SkipSidecar) {
    Write-Host "Step 2/3: Building Python sidecar bundle..." -ForegroundColor Yellow
    Set-Location $RootDir
    & $pythonCommand.Source scripts/build_sidecar.py `
        --root "$RootDir" `
        --out "$SidecarBundle" `
        --python-version 3.12
    Assert-NativeCommandSucceeded "Python sidecar build"
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
    cargo tauri build -c tauri.dev-bundled.conf.json --bundles msi --verbose
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
        cargo tauri build --bundles msi --config $configOverride --verbose
    } else {
        cargo tauri build --bundles msi --verbose
    }
}
Assert-NativeCommandSucceeded "Tauri MSI build"

# List the MSI files if they exist
$msiDir = Join-Path $DesktopDir "src-tauri\target\release\bundle\msi"
$msiArtifacts = @()
if (Test-Path $msiDir) {
    $msiArtifacts = @(Get-ChildItem $msiDir -Filter *.msi -File)
}
if (-not $msiArtifacts) {
    throw "Tauri exited successfully, but no MSI artifact was found in '$msiDir'."
}

if ($CertificateThumbprint) {
    foreach ($artifact in $msiArtifacts) {
        $signature = Get-AuthenticodeSignature $artifact.FullName
        if ($signature.Status -ne "Valid") {
            throw "Invalid Authenticode signature on '$($artifact.FullName)': $($signature.Status)"
        }
    }
    Write-Host "Authenticode signatures verified." -ForegroundColor Green
}

Write-Host ""
Write-Host "Generated MSI files:" -ForegroundColor Cyan
$msiArtifacts | Format-Table Name, Length, LastWriteTime
Write-Host "Output: $msiDir"
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
