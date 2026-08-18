# Desktop packaging and signing

Last reviewed: 2026-08-18.

## Audit summary

- The three previous workflow files were fully commented out, so GitHub did
  not register or run any CI or packaging workflow.
- The old Intel build used `macos-13`. GitHub's current standard Intel label is
  `macos-15-intel`; Apple Silicon uses `macos-15` (arm64).
- The old build and release workflows duplicated nearly all packaging logic.
- The old build workflow omitted the Intel target, while the old release
  workflow included it.
- Each package contains a native CPython runtime and native Python wheels.
  Consequently, each sidecar must be built on the same OS and architecture as
  its desktop package. Presentation rendering reuses the app's system WebView,
  so no browser runtime is bundled in the sidecar.
- `bundle.macOS.signingIdentity` was fixed to `"-"`, which is only an ad-hoc
  signature. It cannot establish a verified developer identity or satisfy
  notarization requirements.
- The old workflows had no certificate import, notarization credentials,
  signature verification, architecture verification, or checksums.
- A local audit build found a stale `rw.*.dmg` in the macOS bundle directory.
  Tauri treated it as DMG source content, producing an oversized image that
  failed to detach. The consolidated workflow removes stale bundle outputs
  before every package build.
- The first hosted Intel run also exposed an intermittent DiskArbitration
  timeout in Tauri's mount-and-detach DMG creator. The workflow now builds the
  app bundle with Tauri and creates the compressed DMG directly with
  `hdiutil -srcfolder`, which does not mount a temporary volume.
- The custom no-UAC MSI installed under `LocalAppDataFolder`. WiX 3's ICE38
  validation correctly rejected Tauri-generated file key paths in the user
  profile, and Tauri does not currently support pure per-user MSI authoring.
  Windows packaging now uses Tauri's supported NSIS `currentUser` mode instead
  of suppressing MSI validation rules.
- `TAURI_SKIP_FRONTEND_BUILD` was set even though it is not part of the
  application build contract. The consolidated workflow lets Tauri run the
  configured `beforeBuildCommand` once.
- The release/signing documentation pointer referenced a file that did not
  exist. It now points to this document.

## Consolidated workflow

`.github/workflows/desktop-packages.yml` is the only GitHub Actions workflow.
Run it from **Actions > Build desktop packages > Run workflow** for an
unpublished package audit. Pushing a version tag such as `v0.0.7` builds all
targets, creates signed updater artifacts, generates `latest.json`, and
publishes the GitHub Release. The `platform` input for manual runs can build
all three targets or only `macos-intel`,
`macos-apple-silicon`, or `windows-x64`. The selected matrix produces these
artifacts:

| Job | Runner | Native architecture | Artifact |
| --- | --- | --- | --- |
| DMG · Intel | `macos-15-intel` | x86_64 | `evoflux-macos-intel` |
| DMG · Apple Silicon | `macos-15` | arm64 | `evoflux-macos-apple-silicon` |
| NSIS · Windows x64 | `windows-2022` | x86_64 | `evoflux-windows-x64` |

Every artifact includes a SHA-256 checksum. DMG jobs verify the Mach-O
architecture, app signature, and disk-image checksum. Developer ID-signed
macOS jobs additionally verify the DMG signature and stapled notarization
ticket. The Windows job installs the NSIS package silently into empty app-data
directories, launches the installed executable, and requires its bundled
backend to become ready. This covers the real installer layout, Rust
supervisor, and first database/config initialization. Signed Windows jobs also
validate the NSIS installer Authenticode signature.

The `signing` input has three modes:

- `auto` (default): use production signing only when every secret required by
  that platform is available. Otherwise build ad-hoc DMGs and an unsigned NSIS
  installer.
- `required`: fail a platform job immediately when any signing secret is
  missing. Use this for a real public release.
- `off`: always build ad-hoc DMGs and an unsigned NSIS installer.

## In-app updates from GitHub Releases

Packaged release builds check
`https://github.com/evoelsewhere/evoflux/releases/latest/download/latest.json`
after startup and when the user chooses **Check for Updates** from Settings,
the application menu, or the tray menu. Tauri compares semantic versions,
downloads only the current OS/architecture artifact, verifies its updater
signature, installs it, and restarts EvoFlux. Development builds and manual
audit builds without the updater key have update checks disabled.

Updater signing is independent from Apple Developer ID and Windows
Authenticode signing. It is free and is required even while the outer packages
remain ad-hoc/unsigned: it prevents a modified GitHub asset or manifest from
being installed over an existing EvoFlux copy.

Provision the updater key once from the repository root:

```bash
./scripts/generate_updater_keys.sh
gh secret set TAURI_SIGNING_PUBLIC_KEY < .tauri-keys/EvoFlux.key.pub
gh secret set TAURI_SIGNING_PRIVATE_KEY < .tauri-keys/EvoFlux.key
# Only when the private key was generated with a password:
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD
```

Back up the private key and password before publishing the first updater-aware
release. Losing or rotating this key prevents already-installed copies from
accepting future updates. A tagged release fails before packaging when the
public or private updater key secret is missing.

Tauri produces a signed `.app.tar.gz` for each macOS architecture and a
signature next to the Windows NSIS installer. The release job renames the
macOS archives with architecture suffixes, builds a static `latest.json`,
uploads all packages/signatures/checksums, then publishes the draft release.
The first updater-aware version is a bootstrap release: users on older builds
must install it manually once; subsequent versions update in-app.

## macOS Developer ID signing and notarization

Distribution outside the Mac App Store requires a paid Apple Developer Program
membership, a **Developer ID Application** certificate, and notarization. A
free Apple Developer account cannot notarize an application.

1. Create a CSR in Keychain Access and ask the Apple Developer account holder
   to create a `Developer ID Application` certificate.
2. Install the certificate, expand it under **My Certificates**, and export the
   certificate plus private key as a password-protected `.p12` file.
3. Find the exact signing identity:

   ```bash
   security find-identity -v -p codesigning
   ```

4. Create an App Store Connect API key with Developer access. Record the
   Issuer ID and Key ID and download the `.p8` private key (Apple permits only
   one download).
5. Configure these GitHub Actions repository secrets:

| Secret | Value |
| --- | --- |
| `APPLE_CERTIFICATE` | Single-line base64 of the exported `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | `.p12` export password |
| `APPLE_SIGNING_IDENTITY` | Exact `Developer ID Application: ... (TEAMID)` identity |
| `APPLE_API_ISSUER` | App Store Connect issuer ID |
| `APPLE_API_KEY` | App Store Connect key ID |
| `APPLE_API_KEY_BASE64` | Single-line base64 of the downloaded `.p8` |

Create the base64 values without line wrapping:

```bash
openssl base64 -A -in DeveloperID.p12 -out DeveloperID.p12.base64
openssl base64 -A -in AuthKey_KEYID.p8 -out AuthKey_KEYID.p8.base64
gh secret set APPLE_CERTIFICATE < DeveloperID.p12.base64
gh secret set APPLE_CERTIFICATE_PASSWORD --body '<p12-password>'
gh secret set APPLE_SIGNING_IDENTITY --body 'Developer ID Application: Example (TEAMID)'
gh secret set APPLE_API_ISSUER --body '<issuer-id>'
gh secret set APPLE_API_KEY --body '<key-id>'
gh secret set APPLE_API_KEY_BASE64 < AuthKey_KEYID.p8.base64
```

Tauri imports the `.p12`, signs and notarizes the app, and staples its ticket.
The workflow then creates the DMG without mounting it, signs the image, submits
it to Apple's notary service, and staples the DMG ticket. The committed
entitlements include JIT, unsigned executable memory, and disabled library
validation; these are broad exceptions required by the embedded runtimes and
should be reviewed whenever the sidecar changes.

## Windows Authenticode signing

The implemented path uses an exportable, password-protected code-signing PFX.
It signs during the Tauri build, which covers the application executable and
the NSIS setup executable, and timestamps the signatures.

1. Purchase a Windows **code-signing** certificate (not a TLS/SSL certificate)
   from a trusted CA.
2. Export it with its private key as a password-protected `.pfx`/`.p12`.
3. Create a single-line base64 value and configure two repository secrets:

   ```powershell
   $bytes = [IO.File]::ReadAllBytes("EvoFlux-code-signing.pfx")
   [Convert]::ToBase64String($bytes) |
     Set-Content -NoNewline "EvoFlux-code-signing.pfx.base64"
   Get-Content -Raw "EvoFlux-code-signing.pfx.base64" |
     gh secret set WINDOWS_CERTIFICATE
   gh secret set WINDOWS_CERTIFICATE_PASSWORD `
     --body '<pfx-password>'
   ```

The workflow imports the PFX into the ephemeral runner's current-user
certificate store, derives its thumbprint, gives that thumbprint to Tauri, and
checks the resulting setup executable with `Get-AuthenticodeSignature`.

Many new OV/EV certificates are issued with non-exportable private keys on a
hardware token or managed signing service. Those certificates cannot use the
PFX workflow above. For that case, use Tauri's `bundle.windows.signCommand`
with one of these services:

- Azure Artifact Signing (formerly Azure Trusted Signing), using
  `artifact-signing-cli` plus Azure workload credentials.
- Azure Key Vault, using a compatible signing client such as `relic`.
- The CA's hardware-token or remote-signing client.

That alternative needs provider-specific account, endpoint, certificate
profile, and identity values. Do not add placeholder cloud credentials to the
workflow; select a provider first, then configure a custom sign command and
prefer GitHub OIDC/workload identity over a long-lived Azure client secret when
the provider supports it.

## References

- [Tauri macOS code signing](https://v2.tauri.app/distribute/sign/macos/)
- [Tauri Windows code signing](https://v2.tauri.app/distribute/sign/windows/)
- [GitHub-hosted runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [Apple Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)
- [Apple notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Microsoft SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)
- [Azure Artifact Signing](https://learn.microsoft.com/en-us/azure/artifact-signing/)
