"""Optional local speech-to-text runtime lifecycle."""

from app.services.local_stt_runtime.installer import (
    LocalSttRuntimeError,
    cancel_install,
    check_runtime,
    dismiss_error,
    runtime_status,
    start_install,
    uninstall_runtime,
)

__all__ = [
    "LocalSttRuntimeError",
    "cancel_install",
    "check_runtime",
    "dismiss_error",
    "runtime_status",
    "start_install",
    "uninstall_runtime",
]
