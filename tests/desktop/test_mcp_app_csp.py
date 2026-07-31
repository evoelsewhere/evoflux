from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _security(path: str) -> dict:
    config = json.loads((ROOT / path).read_text())
    return config["app"]["security"]


def _csp(path: str) -> dict[str, str]:
    return _security(path)["csp"]


def _exists(path: str) -> bool:
    return (ROOT / path).exists()


def test_desktop_csp_allows_general_mcp_app_resources_in_production() -> None:
    csp = _csp("desktop/src-tauri/tauri.conf.json")

    assert csp["default-src"] == "'self'"
    assert "http:" in csp["connect-src"]
    assert "https:" in csp["connect-src"]
    assert "wss:" in csp["connect-src"]
    assert "blob:" in csp["script-src"]
    assert "data:" in csp["script-src"]
    assert "http:" in csp["script-src"]
    assert "https:" in csp["script-src"]
    assert "'unsafe-eval'" in csp["script-src"]
    assert "http:" in csp["style-src"]
    assert "https:" in csp["style-src"]
    assert "http:" in csp["font-src"]
    assert "https:" in csp["font-src"]
    assert "about:" in csp["frame-src"]
    assert "blob:" in csp["frame-src"]
    assert "data:" in csp["frame-src"]
    assert "http:" in csp["frame-src"]
    assert "https:" in csp["frame-src"]


@pytest.mark.skipif(
    not _exists("mobile/src-tauri/tauri.conf.json"),
    reason="mobile/src-tauri not present",
)
def test_mobile_csp_allows_general_mcp_app_frames_in_production() -> None:
    csp = _csp("mobile/src-tauri/tauri.conf.json")

    assert "about:" in csp["frame-src"]
    assert "blob:" in csp["frame-src"]
    assert "data:" in csp["frame-src"]
    assert "http:" in csp["frame-src"]
    assert "https:" in csp["frame-src"]
    assert "blob:" in csp["script-src"]
    assert "'unsafe-eval'" in csp["script-src"]
    assert "https:" in csp["script-src"]
    assert "https:" in csp["connect-src"]


def test_prod_asset_csp_modification_keeps_unsafe_inline_effective() -> None:
    """Tauri injects script hashes/nonces into bundled assets' CSP at build
    time.  Any hash/nonce in script-src makes browsers IGNORE 'unsafe-inline',
    which the srcdoc-based MCP app iframe inherits — blanking MCP UI apps
    (e.g. excalidraw) in production builds while dev (external URL, no CSP
    injection) keeps working.  Disabling asset CSP modification for
    script-src/style-src keeps 'unsafe-inline' effective in prod.
    """
    paths = ["desktop/src-tauri/tauri.conf.json"]
    if _exists("mobile/src-tauri/tauri.conf.json"):
        paths.append("mobile/src-tauri/tauri.conf.json")
    for path in paths:
        security = _security(path)
        disabled = security.get("dangerousDisableAssetCspModification")
        assert disabled is True or (
            isinstance(disabled, list)
            and "script-src" in disabled
            and "style-src" in disabled
        ), f"{path}: asset CSP modification must be disabled for script-src/style-src"
