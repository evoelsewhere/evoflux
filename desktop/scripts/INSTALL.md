# Installing EvoFlux

EvoFlux ships as an **unsigned** desktop application. There's no
malware here — we just haven't paid Apple/Microsoft for code-signing
certificates yet — but the major operating systems treat unsigned
software with suspicion. This document explains the one-time steps
required on each platform.

## macOS (arm64)

1. Open the downloaded **`EvoFlux-x.y.z.dmg`** by double-clicking it.
2. Open **`Terminal`** from the DMG (or your own Terminal app) and
   run:

   ```bash
   /Volumes/EvoFlux/install.sh --install
   ```

   The script will:
   - Strip the `com.apple.quarantine` xattr that the browser added.
   - Ad-hoc codesign the bundle locally (no Apple ID required).
   - Verify the signature.
   - Copy `EvoFlux.app` into `/Applications/`.

3. Launch **EvoFlux** from Launchpad / Spotlight. The first time
   you run it, **right-click → Open** and confirm the prompt.
   macOS will remember the consent.

**Why is this necessary?** Without a paid Apple Developer ID, the
DMG comes through unsigned. Gatekeeper then reports
*"EvoFlux.app is damaged and can't be opened"* — which is a lie,
but the only way to clear it is to either pay Apple $99/year or
ad-hoc sign the bundle on your own machine. We chose option B for
v1; option A may come later.

**Already have an Apple Developer ID and want to re-sign with it?**
The script refuses to overwrite an existing signature; pass
`--force` to clobber.

## Linux (x86_64, arm64)

We ship three artifacts; pick whichever your distro prefers.

### AppImage (universal)

```bash
chmod +x EvoFlux-x.y.z.AppImage
./install.sh --install ./EvoFlux-x.y.z.AppImage
```

This installs the binary to `~/.local/bin/EvoFlux`, drops a
`.desktop` entry under `~/.local/share/applications/`, and registers
the icon with the hicolor theme. No `sudo` required.

If `~/.local/bin` is not on your `$PATH`, the script will print the
exact `export` line to add to your shell rc.

### Debian / Ubuntu (`.deb`)

```bash
sudo dpkg -i EVOFLUX_x.y.z_amd64.deb
sudo apt-get install -f      # only if dpkg complains about deps
```

### Fedora / RHEL (`.rpm`)

```bash
sudo rpm -Uvh EvoFlux-x.y.z.x86_64.rpm
```

The `install.sh` helper detects `.deb` / `.rpm` and defers to the
right package manager automatically.

## Windows (x64)

Run **`EvoFlux-x.y.z-x64.msi`**.

Windows SmartScreen will show
*"Windows protected your PC"* on the first launch. Click
**"More info"** → **"Run anyway"**. You only need to do this once.

The MSI installer handles:

- Copying files to `%LOCALAPPDATA%\Programs\EvoFlux\`.
- Creating Start Menu and Desktop shortcuts.
- Registering the uninstaller in *Settings → Apps*.

To uninstall: *Settings → Apps → EvoFlux → Uninstall*.

## Verifying the download (all platforms)

Every release publishes a `SHA256SUMS` file. Verify before installing:

```bash
# macOS / Linux
shasum -a 256 -c SHA256SUMS

# Windows (PowerShell)
Get-FileHash -Algorithm SHA256 EvoFlux-*.msi
```

The expected hashes are also pinned in the GitHub release notes.

## Uninstall

| Platform | How                                                                  |
|----------|----------------------------------------------------------------------|
| macOS    | Drag `EvoFlux.app` from `/Applications` to the Trash.             |
| Linux    | Delete `~/.local/bin/EvoFlux` and `~/.local/share/applications/EvoFlux.desktop`. Or `sudo apt remove EvoFlux` / `sudo rpm -e EvoFlux` if you used the system package. |
| Windows  | *Settings → Apps → EvoFlux → Uninstall*.                          |

Application data lives under the same XDG paths used by the CLI (these survive uninstall by design):

- Config: `~/.config/EvoFlux/`
- Data: `~/.local/share/EvoFlux/`
- Wiki: `~/.local/share/EvoFlux-wiki/`
- Workspace: `~/.local/share/EvoFlux-workspace/`
- State/logs: `~/.local/state/EvoFlux/`
- Cache/OAuth: `~/.cache/EvoFlux/`

Delete those directories manually if you want a clean slate.

## Troubleshooting

### macOS: "the developer cannot be verified"

You didn't right-click → Open on first launch. Run:

```bash
xattr -dr com.apple.quarantine /Applications/EvoFlux.app
```

and try again.

### macOS: app launches but immediately quits

Most likely a native dependency failed JIT initialization because the
`com.apple.security.cs.allow-unsigned-executable-memory` entitlement got
stripped. Re-run `install.sh` — it re-applies the correct entitlements every
time.

### Linux: "EvoFlux: command not found" after install

`~/.local/bin` isn't on your `$PATH`. Add to `~/.bashrc` /
`~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Reload your shell. Or just launch from the desktop menu.

### Windows: SmartScreen blocked the MSI

Click **"More info"** in the dialog, then **"Run anyway"**. The
binary is unsigned (we don't have a code-signing cert yet) but
its SHA256 matches the one published on GitHub.
