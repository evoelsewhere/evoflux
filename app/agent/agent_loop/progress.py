"""Opt-in run-local detection of repeated, unchanged read observations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

_TRACKER_KEY = "_tool_progress_evidence"


class ToolProgressTracker:
    """Track unchanged outcomes only for tools with explicit safe-read metadata."""

    def _identity(self, tool: Any, args: dict[str, Any]) -> tuple[str, str] | None:
        scope_builder = getattr(tool, "progress_scope", None)
        if not getattr(tool, "read_only", False) or not callable(scope_builder):
            return None
        try:
            raw_scope = scope_builder(args)
        except Exception as exc:  # noqa: BLE001 - the guard must fail open
            logger.warning(
                "tool_progress_scope_failed tool={} error={}", tool.name, exc
            )
            return None
        if not isinstance(raw_scope, str) or not raw_scope.strip():
            return None
        try:
            serialized_args = json.dumps(
                args, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except (TypeError, ValueError):
            return None
        scope_hash = hashlib.sha256(
            f"{tool.name}\0{raw_scope}".encode("utf-8", errors="replace")
        ).hexdigest()
        args_hash = hashlib.sha256(serialized_args.encode("utf-8")).hexdigest()
        return scope_hash, args_hash

    def should_block(
        self, tool: Any, args: dict[str, Any], metadata: dict[str, Any]
    ) -> str | None:
        """Return guidance after repeated equal outcomes across arguments."""

        identity = self._identity(tool, args)
        if identity is None:
            return None
        scope_hash, args_hash = identity
        records = metadata.get(_TRACKER_KEY)
        if not isinstance(records, dict):
            return None
        record = records.get(scope_hash)
        if not isinstance(record, dict):
            return None
        repeated = int(record.get("same_outcome_count", 0)) >= 2
        error_policy = record.get("error_policy")
        if record.get("is_error"):
            enough_evidence = (
                error_policy == "terminal"
                and int(record.get("same_outcome_count", 0)) >= 1
            ) or (error_policy == "retry_once" and repeated)
        else:
            recorded_arguments = record.get("argument_hashes", [])
            enough_evidence = repeated and (
                args_hash in recorded_arguments or len(recorded_arguments) >= 2
            )
        if not enough_evidence:
            return None
        metadata["tool_progress_blocks"] = (
            int(metadata.get("tool_progress_blocks", 0)) + 1
        )
        evidence = (
            "The tool classified this read error as terminal."
            if record.get("is_error") and error_policy == "terminal"
            else "The same transient read error repeated after one retry."
            if record.get("is_error")
            else "Two different argument sets for this read target returned identical evidence."
        )
        return (
            "[Tool call stopped — no progress detected]\n"
            f"tool: {tool.name}\n"
            f"{evidence} Do not issue another variation of the same read. Use a "
            "different source or target, or summarize the evidence already gathered. "
            "This block applies only to this run and this explicitly tracked read scope."
        )

    def record(
        self,
        tool: Any,
        args: dict[str, Any],
        result: str,
        metadata: dict[str, Any],
    ) -> None:
        """Record an outcome, resetting a scope when its result changes."""
        is_error = result.startswith("Error:")
        error_policy = None
        if is_error:
            classifier = getattr(tool, "progress_error_policy", None)
            if not callable(classifier):
                self._reset_scope(tool, args, metadata)
                return
            try:
                error_policy = classifier(result)
            except Exception as exc:  # noqa: BLE001 - classification must fail open
                logger.warning(
                    "tool_progress_error_policy_failed tool={} error={}", tool.name, exc
                )
                self._reset_scope(tool, args, metadata)
                return
            if error_policy not in {"terminal", "retry_once"}:
                self._reset_scope(tool, args, metadata)
                return
        self.record_digest(
            tool,
            args,
            hashlib.sha256(result.encode("utf-8", errors="replace")).hexdigest(),
            metadata,
            is_error=is_error,
            error_policy=error_policy,
        )

    def _reset_scope(
        self, tool: Any, args: dict[str, Any], metadata: dict[str, Any]
    ) -> None:
        """Avoid treating a later success as continuous evidence across an error."""

        identity = self._identity(tool, args)
        records = metadata.get(_TRACKER_KEY)
        if identity is not None and isinstance(records, dict):
            records.pop(identity[0], None)

    def record_digest(
        self,
        tool: Any,
        args: dict[str, Any],
        result_hash: str,
        metadata: dict[str, Any],
        *,
        is_error: bool = False,
        error_policy: str | None = None,
    ) -> None:
        """Record an outcome when only its trusted content digest is available."""
        identity = self._identity(tool, args)
        if identity is None:
            return
        scope_hash, args_hash = identity
        records = metadata.setdefault(_TRACKER_KEY, {})
        if not isinstance(records, dict):
            return
        previous = records.get(scope_hash)
        if not isinstance(previous, dict):
            same_outcome_count = 1
            argument_hashes = [args_hash]
        elif previous.get("result_hash") == result_hash:
            same_outcome_count = int(previous.get("same_outcome_count", 1)) + 1
            argument_hashes = list(previous.get("argument_hashes", []))
            if args_hash not in argument_hashes and len(argument_hashes) < 2:
                argument_hashes.append(args_hash)
        else:
            same_outcome_count = 1
            argument_hashes = [args_hash]
        records[scope_hash] = {
            "argument_hashes": argument_hashes,
            "result_hash": result_hash,
            "same_outcome_count": same_outcome_count,
            "is_error": is_error,
            "error_policy": error_policy,
        }

    @staticmethod
    def snapshot(metadata: dict[str, Any]) -> dict[str, int]:
        """Return privacy-safe summary metrics for an evaluation record."""

        records = metadata.get(_TRACKER_KEY)
        return {
            "scopes": len(records) if isinstance(records, dict) else 0,
            "blocked": int(metadata.get("tool_progress_blocks", 0)),
        }


progress_tracker = ToolProgressTracker()
