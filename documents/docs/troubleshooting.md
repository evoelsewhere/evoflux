# Troubleshooting

Common install and runtime issues. Run `evoflux doctor` for install checks, or `evoflux health` for backend connectivity checks.

## Desktop app (most users)

### macOS — `EvoFlux.app` is damaged and can't be opened

Gatekeeper is blocking the unsigned app bundle. Use the Homebrew cask instead:

```bash
brew install --cask khuonghung/tap/evoflux
```

Or mount the DMG and run the bundled installer:

```bash
./install.sh
```

If you dragged the app to `/Applications`, re-run the installer against the installed bundle:

```bash
./install.sh /Applications/evoflux.app --force
```

### Linux — AppImage won't launch

Make it executable first:

```bash
chmod +x EVOFLUX_*_amd64.AppImage
```

### In-app updater stuck on `Checking...`

Go to **Settings → About → Updates**, click **Cancel**, then try again. If it still hangs, use `brew upgrade --cask EvoFlux` on macOS or reinstall from the latest release.

### Desktop notifications don't appear

Open **Settings → Notifications**, enable notifications, and send a test notification. Also check the OS permission at **System Settings → Notifications → EvoFlux**.

## CLI / server (developers)

These troubleshooting steps apply if you're running EvoFlux as a CLI or server (`EvoFlux`). If you installed the desktop app, see the Desktop app section above.

## `command not found: EvoFlux` after pip install

Make sure your Python scripts directory is on `PATH`. Try `python -m app.cli` as a fallback, or install with `uv tool install $1evoflux` (which manages PATH for you).

## `command not found: uv`

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## `command not found: bun` (development only)

Install Bun:

```bash
curl -fsSL https://bun.sh/install | bash
```

Bun is only needed for development. Production installs (`pip install`) don't require it.

## Server starts but the web UI shows a blank page

The FastAPI server is API-only and does not serve the React app. Use the desktop app for the packaged UI, or use `make dev` from a source checkout — it starts uvicorn (:8000) and the Vite dev server (:5173) together with hot-reload.

## `GOOGLE_API_KEY not set` or similar provider errors

Copy `.env.example` to the correct location (see [Configuration](configuration.md)) and add your API key. At least one LLM provider key is required.

## Gemini `400 INVALID_ARGUMENT` — unknown field in function declarations

The Gemini API rejects JSON Schema fields it doesn't recognise (`discriminator`, `const`, `exclusiveMinimum`, `additionalProperties`, etc.) in tool schemas. `GeminiProviderBase._sanitize_schema()` strips these automatically — if you see this error it likely means a tool schema contains a new unsupported field. Add it to `_UNSUPPORTED_SCHEMA_KEYS` in `app/agent/providers/googlegenai/googlegenai.py`. See [Gemini schema sanitization](agent/tools.md#gemini-schema-sanitization) for the full list.

## SQLite `database is locked` errors

Usually means two server instances are running. Run `evoflux restart`; add `--lan --key` if LAN clients need access and the server has not been configured for it yet.

## MCP stdio server fails with `ExceptionGroup` or `FileNotFoundError`

If an MCP server configured with stdio (e.g., using `npx` or `uvx`) fails to start:
- Make sure the command is installed and available in your terminal.
- The desktop app automatically resolves your terminal's `PATH` by querying your login shell. If you just installed the tool, click **Restart** on the MCP server in the settings UI to trigger a dynamic re-detection of your `PATH` without restarting the desktop app.

## Related

- [Install](install.md)
- [CLI reference](cli.md)
- [Configuration](configuration.md)
