"""Windows onnxruntime native preload shim.

On Python 3.14 / Windows the ``onnxruntime`` wheel fails to import with::

    ImportError: DLL load failed while importing onnxruntime_pybind11_state:
    A dynamic link library (DLL) initialization routine failed.  (error 1114)

The cause is a load-order conflict: once SQLAlchemy's compiled Cython
extensions are imported, loading ``onnxruntime.dll`` as a *static* dependency of
the pybind extension runs its ``DllMain`` under the loader lock and fails. If
``onnxruntime.dll`` is loaded up front via ``LoadLibrary`` (ctypes) — before the
conflicting extensions — its initialiser runs cleanly and every later
``import onnxruntime`` reuses the already-initialised module.

This shim must therefore run *early*, before SQLAlchemy is imported (see
``app/server.py``). It is a no-op on non-Windows platforms and whenever the DLLs
are absent or already loaded, so it is always safe to call.

This module lives directly under the ``app`` namespace package (no package
``__init__`` side effects) so importing it cannot itself pull in SQLAlchemy.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from loguru import logger


@lru_cache(maxsize=1)
def preload_onnxruntime() -> bool:
    """Preload onnxruntime's native DLLs on Windows. Returns True if attempted.

    Best-effort and idempotent: any failure is logged at debug level and
    swallowed so callers can still attempt the normal import and surface a
    meaningful error if it genuinely cannot load.

    This must run *early*, before the conflicting C extensions initialise. If
    they are already loaded the load-order conflict is irreversible and force
    -loading onnxruntime.dll then can hard-crash the process (access violation
    under the loader lock with live threads), so we refuse to act in that case.
    """
    if sys.platform != "win32":
        return False

    # If a conflicting native extension is already imported it is too late to
    # preload safely — skip rather than risk crashing the interpreter. onnxruntime
    # already loaded means there is nothing to do either way.
    if any(m in sys.modules for m in ("sqlalchemy", "truststore", "onnxruntime")):
        return False

    import ctypes
    import importlib.util
    from pathlib import Path

    try:
        spec = importlib.util.find_spec("onnxruntime")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.origin:
        return False

    capi = Path(spec.origin).parent / "capi"
    if not capi.is_dir():
        return False

    # Load every sibling .dll (not the .pyd) so the extension import reuses the
    # already-initialised modules instead of loading them under the loader lock.
    for dll in sorted(capi.glob("*.dll")):
        try:
            ctypes.WinDLL(str(dll))
        except OSError as exc:  # pragma: no cover - platform/env specific
            logger.debug("onnxruntime preload skipped dll={} err={}", dll.name, exc)
    return True
