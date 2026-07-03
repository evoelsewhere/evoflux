"""Module entry point so ``python -m app.cli`` works.

This is what the desktop sidecar invokes — see ``desktop/src-tauri/src/sidecar.rs``.
The console-script ``EvoFlux`` defined in ``pyproject.toml`` calls the
same :func:`app.cli.main.main` function via a generated wrapper, but the
desktop shell can't rely on a wrapper script existing on PATH inside a
bundled site-packages directory.
"""

from __future__ import annotations

from app.cli.main import main

if __name__ == "__main__":
    main()
