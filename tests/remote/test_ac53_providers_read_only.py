"""AC-53 inspection test: no remote code path may reach a credential-
accepting provider endpoint.

A behavioral test could only prove the paths it thinks to exercise; a
static scan proves the *absence* of a reference anywhere in the package,
which is what AC-53 actually promises ("proven by an inspection test
over the remote dispatch surface", not by convention or by enumerating
every possible callback).

Scans the AST rather than raw text so a docstring or comment that merely
*names* one of these functions (e.g. control.py's own module docstring,
documenting that it does NOT call them) never counts as a reference —
only an actual import, call, or attribute access does.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REMOTE_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "app" / "remote"

#: Every provider endpoint in app/api/routes/settings.py that accepts or
#: mutates credentials, visibility, or existence — AC-53's "no remote
#: path reaches PUT .../providers/{id}, POST .../test, or any other
#: credential-accepting endpoint".
_WRITE_CAPABLE_PROVIDER_FUNCTIONS = (
    "save_provider",
    "save_provider_visible_models",
    "test_provider",
    "list_provider_models",
    "delete_provider",
)


def _remote_source_files() -> list[Path]:
    assert _REMOTE_PACKAGE_ROOT.is_dir(), _REMOTE_PACKAGE_ROOT
    return list(_REMOTE_PACKAGE_ROOT.rglob("*.py"))


def _referenced_identifiers(path: Path) -> set[str]:
    """Every real Python identifier a file's code actually binds to or
    reads — import targets, attribute accesses, bare names — never string
    literals, docstrings, or comments (comments never reach the AST at
    all; docstrings are Constant nodes, not Name/Attribute/alias)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.alias):
            identifiers.add(node.name)
    return identifiers


def test_no_remote_source_file_references_a_write_capable_provider_function() -> None:
    files = _remote_source_files()
    assert len(files) > 10  # sanity: the glob actually found the package

    offenders: list[str] = []
    for path in files:
        identifiers = _referenced_identifiers(path)
        for name in _WRITE_CAPABLE_PROVIDER_FUNCTIONS:
            if name in identifiers:
                offenders.append(f"{path.relative_to(_REMOTE_PACKAGE_ROOT)}: {name}")

    assert offenders == []


def test_slash_commands_do_not_include_a_provider_write_command() -> None:
    from app.remote.actions import _SLASH_COMMANDS

    # A future "/providers" command must stay a read-only view — nothing in
    # today's bounded command set (AC-58) implies a write, and this guards
    # against one being added under a name that sounds like a listing.
    assert "provider" not in {cmd.lower() for cmd in _SLASH_COMMANDS}
    assert "providers" not in {cmd.lower() for cmd in _SLASH_COMMANDS}
