"""EvoFlux-owned Agent Plugin extension namespaces."""

from __future__ import annotations

from collections.abc import Mapping


EVOFLUX_EXTENSION_NAMESPACE = "org.evoelsewhere.evoflux"
CREDENTIALS_EXTENSION = f"{EVOFLUX_EXTENSION_NAMESPACE}.credentials"
MCP_EXTENSION = f"{EVOFLUX_EXTENSION_NAMESPACE}.mcp"
BUILTIN_EXTENSION = f"{EVOFLUX_EXTENSION_NAMESPACE}.builtin"

# These pre-canonical names shipped before EvoFlux adopted a reverse-domain
# namespace. Keep them readable so existing installed plugins do not break.
LEGACY_CREDENTIALS_EXTENSIONS = ("evoflux.credentials",)
LEGACY_MCP_EXTENSIONS = ("evoflux.mcp",)


def resolve_extension(
    extensions: Mapping[str, dict],
    canonical: str,
    legacy_aliases: tuple[str, ...],
) -> dict | None:
    """Return an extension declaration, preferring the canonical namespace."""

    for namespace in (canonical, *legacy_aliases):
        value = extensions.get(namespace)
        if value is not None:
            return value
    return None


__all__ = [
    "BUILTIN_EXTENSION",
    "CREDENTIALS_EXTENSION",
    "EVOFLUX_EXTENSION_NAMESPACE",
    "LEGACY_CREDENTIALS_EXTENSIONS",
    "LEGACY_MCP_EXTENSIONS",
    "MCP_EXTENSION",
    "resolve_extension",
]
