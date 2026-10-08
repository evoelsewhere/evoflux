"""Argument coercions shared by tool schemas.

Models routinely get one thing wrong about a list parameter: they send the
single element where the schema asks for an array (``"explorer"`` for
``["explorer"]``), or a JSON array that was encoded a second time. Both are
unambiguous, and rejecting them costs a turn per mistake and a retry the model
may repeat verbatim, so a list parameter reads them as the list they mean.

The advertised JSON schema is unchanged — it still says ``array`` — so this
widens only what is accepted, never what the model is told to send.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BeforeValidator


def coerce_str_list(value: Any) -> Any:
    """Read a lone string as the list it stands for.

    - ``'["a", "b"]'`` (a double-encoded array) becomes ``["a", "b"]``.
    - ``"a"`` becomes ``["a"]``; a blank string becomes ``[]``.

    Anything that is not a string is returned untouched for Pydantic to judge.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            return [text]
        if isinstance(decoded, list):
            return decoded
    return [text]


#: ``list[str]`` that also accepts a lone string or a double-encoded array.
StrList = Annotated[list[str], BeforeValidator(coerce_str_list)]
