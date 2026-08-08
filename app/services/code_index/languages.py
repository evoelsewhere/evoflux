"""Search-only language coverage for the repository code index."""

from __future__ import annotations

from pathlib import Path

SEARCH_ONLY_LANGUAGES: dict[str, str] = {
    ".bash": "shell",
    ".css": "css",
    ".dtd": "dtd",
    ".f": "fortran",
    ".f03": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".htm": "html",
    ".html": "html",
    ".json": "json",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".scss": "scss",
    ".sh": "shell",
    ".sol": "solidity",
    ".sql": "sql",
    ".toml": "toml",
    ".txt": "text",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "shell",
}


def fallback_language(path: str) -> str | None:
    return SEARCH_ONLY_LANGUAGES.get(Path(path).suffix.casefold())


__all__ = ["SEARCH_ONLY_LANGUAGES", "fallback_language"]
