"""Workflow templating — ``{{ ... }}`` over dotted paths + two filters.

Deliberately tiny (plan §4.3): paths into ``inputs.*``,
``nodes.<id>.output(.dotted.path)``, ``env.<NAME>``, plus ``item``/``index``
inside a foreach body. Filters: ``json``, ``truncate:N``. No expressions,
no conditionals — data plumbing only. A path that doesn't resolve raises
:class:`TemplateError` — nodes fail loudly rather than interpolating an
empty string into a prompt or a shell command.
"""

from __future__ import annotations

import json
import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(?P<expr>[^{}]+?)\s*\}\}")


class TemplateError(ValueError):
    """A template referenced something that doesn't exist (or a bad filter)."""


def _lookup(path: str, scope: dict[str, Any]) -> Any:
    current: Any = scope
    for i, part in enumerate(path.split(".")):
        if isinstance(current, dict):
            if part not in current:
                raise TemplateError(
                    f"template path '{path}' does not resolve "
                    f"(missing '{part}' at segment {i + 1})."
                )
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise TemplateError(
                    f"template path '{path}' does not resolve "
                    f"('{part}' is not a valid list index)."
                )
        else:
            raise TemplateError(
                f"template path '{path}' does not resolve "
                f"(segment '{part}' walks into a {type(current).__name__})."
            )
    return current


def _apply_filter(value: Any, spec: str) -> Any:
    name, _, arg = spec.partition(":")
    name = name.strip()
    if name == "json":
        return json.dumps(value, ensure_ascii=False, default=str)
    if name == "truncate":
        try:
            limit = int(arg)
        except ValueError:
            raise TemplateError(f"truncate filter needs an integer, got '{arg}'.")
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        return text if len(text) <= limit else text[:limit].rstrip() + "…"
    raise TemplateError(f"unknown template filter '{name}' (have: json, truncate:N).")


def _render_expr(expr: str, scope: dict[str, Any]) -> Any:
    parts = [part.strip() for part in expr.split("|")]
    value = _lookup(parts[0], scope)
    for filter_spec in parts[1:]:
        value = _apply_filter(value, filter_spec)
    return value


def render(template: str, scope: dict[str, Any]) -> str:
    """Render every ``{{...}}`` in *template* against *scope*.

    A template that is EXACTLY one placeholder returns the resolved value
    with its original type (so ``items: "{{nodes.plan.output.repos}}"`` can
    yield a real list); anything with surrounding text stringifies each
    placeholder.
    """
    exact = _PLACEHOLDER_RE.fullmatch(template.strip())
    if exact:
        return _render_expr(exact.group("expr"), scope)

    def _sub(match: re.Match[str]) -> str:
        value = _render_expr(match.group("expr"), scope)
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    return _PLACEHOLDER_RE.sub(_sub, template)


def render_object(value: Any, scope: dict[str, Any]) -> Any:
    """Recursively render templates inside dicts/lists/strings."""
    if isinstance(value, str):
        return render(value, scope)
    if isinstance(value, dict):
        return {key: render_object(item, scope) for key, item in value.items()}
    if isinstance(value, list):
        return [render_object(item, scope) for item in value]
    return value


def referenced_env_names(value: Any) -> set[str]:
    """Every ``env.<NAME>`` referenced anywhere in *value* — feeds the
    approval manifest (plan §7)."""
    names: set[str] = set()

    def _walk(item: Any) -> None:
        if isinstance(item, str):
            for match in _PLACEHOLDER_RE.finditer(item):
                expr = match.group("expr").split("|")[0].strip()
                if expr.startswith("env."):
                    names.add(expr.split(".", 1)[1].split(".")[0])
        elif isinstance(item, dict):
            for child in item.values():
                _walk(child)
        elif isinstance(item, list):
            for child in item:
                _walk(child)

    _walk(value)
    return names
