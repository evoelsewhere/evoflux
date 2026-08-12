# Build the desktop app and its Python sidecar.
#
# Targets:
#   make sidecar        Build the standard sidecar with [documents].
#   make sidecar-full   Same, but with [documents,azure-doc-intel].
#   make icons          Regenerate .icns / .ico from icons/icon.png.
#   make dev            Tauri shell connected to the source API at :8000.
#                       Run root ``make dev-web`` in another terminal.
#   make dev-bundled    Rebuild and run the Tauri shell with the *bundled*
#                       sidecar. Use this to test the
#                       sidecar handshake / auth wiring end-to-end.
#   make build          Build a release desktop app.
#   make open           Open the dev macOS app bundle.
#   make open-prod      Open the production macOS app bundle.
#   make clean          Remove build artefacts.
#
# Dev-mode two-terminal flow:
#
#     terminal 1:   make dev-web               # source API + Vite
#     terminal 2:   make -C desktop dev        # Tauri → source API
#
# Root ``make dev-desktop`` provides the same flow in one terminal.

.PHONY: sidecar sidecar-full icons dev dev-bundled build-dev-app build clean open open-prod

ROOT       := $(abspath ..)
BUNDLE     := sidecar-bundle
PYVER      := 3.12
EXTRAS     ?= documents             # set to e.g. "documents,azure-doc-intel" or "full"
DEV_BACKEND_URL ?= http://127.0.0.1:8000
sidecar:
	@python3 ../scripts/build_sidecar.py \
		--root "$(ROOT)" \
		--out  "$(BUNDLE)" \
		--python-version "$(PYVER)" \
		$(if $(EXTRAS),--extras "$(EXTRAS)",)

open:
	@open "src-tauri/target/release/bundle/macos/evoflux (dev).app"

open-prod:
	@open "src-tauri/target/release/bundle/macos/evoflux.app"

sidecar-full:
	@$(MAKE) sidecar EXTRAS="documents,azure-doc-intel"

icons:
	cd src-tauri && cargo tauri icon icons/icon.png

# Dev: load the debug WebView from Vite :5173 and force the source backend.
# The explicit override prevents a cached debug sidecar or a saved server
# selection from changing which code this development shell exercises.
#
# ``-c tauri.dev.conf.json`` overrides the bundle identifier + product
# name so the dev build coexists with a Homebrew-cask-installed prod
# build (they get separate Dock icons, tray entries, and log dirs).
# Without this, macOS routes ``open -a evoflux`` to whichever
# instance is already running, masking which app you're testing.
dev:
	@echo "→ Tauri dev shell. Make sure root 'make dev-web' is running. Backend: $(DEV_BACKEND_URL)"
	cd src-tauri && EVOFLUX_DESKTOP_DEV_BACKEND_URL="$(DEV_BACKEND_URL)" cargo tauri dev -c tauri.dev.conf.json

# Dev with the bundled CPython sidecar — the closest thing to ``make build``
# without producing a .dmg. Useful for testing handshake, token injection,
# Job-Object cleanup, and the ``app.cli serve`` entry path.
#
# The XDG roots are pinned to ``<repo>/.evoflux/dev/...`` so bundled-sidecar
# testing stays isolated from the normal source server and production state.
# Without these overrides ``APP_ENV=development`` would resolve them relative
# to the sidecar's cwd (``desktop/src-tauri/``).
dev-bundled:
	@$(MAKE) sidecar
	@rm -rf src-tauri/target/debug/sidecar
	cd src-tauri && \
		EVOFLUX_APP_ENV=development \
		EVOFLUX_DATA_DIR="$(ROOT)/.evoflux/dev/data" \
		EVOFLUX_CONFIG_DIR="$(ROOT)/.evoflux/dev/config" \
		EVOFLUX_STATE_DIR="$(ROOT)/.evoflux/dev/state" \
		EVOFLUX_CACHE_DIR="$(ROOT)/.evoflux/dev/cache" \
		EVOFLUX_WORKSPACE_DIR="$(ROOT)/.evoflux/dev/workspace" \
		EVOFLUX_WIKI_DIR="$(ROOT)/.evoflux/dev/wiki" \
		env -u EVOFLUX_DESKTOP_DEV_BACKEND_URL cargo tauri dev -c tauri.dev-bundled.conf.json

build-dev-app:
	@$(MAKE) sidecar
	cd src-tauri && cargo tauri build -c tauri.dev-bundled.conf.json --bundles app

build:
	cd src-tauri && cargo tauri build

clean:
	rm -rf "$(BUNDLE)" src-tauri/target
