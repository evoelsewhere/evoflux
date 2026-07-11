"""LoopEngine v2 — goal-based, self-healing loop orchestrator.

Adds goal-based termination, prompt evolution, verification hooks,
no-progress detection, token budget, and audit trail on top of the
existing simple "repeat N times" loop.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Literal


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class LoopTurnRecord:
    """Record of a single loop iteration."""

    iteration: int
    prompt: str
    started_at: float  # time.time()
    completed_at: float | None = None
    success: bool | None = None  # None = still running
    tokens_used: int = 0
    error: str | None = None
    error_category: str | None = None  # "recoverable" | "fatal" | None


@dataclass
class LoopConfig:
    """Extended loop configuration."""

    prompt: str
    max_iterations: int = 10
    # Goal-based termination: agent stops when goal is met
    goal: str | None = None
    # Prompt evolution: modify prompt based on previous results.
    # Enabled by default — the whole point of loop engineering is that
    # the loop learns from each iteration rather than blindly repeating.
    evolve_prompt: bool = True
    # Token budget: max total tokens across all iterations
    max_total_tokens: int | None = None
    # No-progress detection: stop after N consecutive failures with same error
    no_progress_threshold: int = 3
    # Verifier command to run after each iteration (e.g., "uv run pytest -q")
    verify_command: str | None = None
    # Max consecutive errors before stopping
    max_consecutive_errors: int = 3
    # Delay between iterations (seconds)
    delay_between_iterations: float = 0.0


@dataclass
class LoopState:
    """Extended loop state — superset of the original LoopState."""

    config: LoopConfig
    remaining: int  # kept for backward compat
    paused: bool = False
    # New fields
    current_iteration: int = 0
    total_tokens_used: int = 0
    consecutive_errors: int = 0
    consecutive_same_error: int = 0
    last_error: str | None = None
    last_error_signature: str | None = None
    turn_history: list[LoopTurnRecord] = field(default_factory=list)
    goal_met: bool = False
    started_at: float | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

# Patterns to strip from error messages when building a signature for
# no-progress comparison.  Strip line numbers, file paths, timestamps,
# memory addresses, PIDs, and UUIDs.
#
# ORDER MATTERS: timestamps (which contain line:col-like subpatterns)
# must be stripped *before* the line:col pattern to avoid mangling them.
_SIGNATURE_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\b"),  # timestamps FIRST
    re.compile(r"(?:at )?line \d+(?:[,:]\s*\d+)?"),  # "line 42" / "at line 10, col 5"
    re.compile(r"\b\d{1,5}:\d{1,5}\b"),  # remaining line:col
    re.compile(r"(/[\w./\-]+)+"),  # POSIX paths
    re.compile(r"[A-Z]:\\[\w\\.\-]+"),  # Windows paths
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),  # UUIDs
    re.compile(r"\b0x[0-9a-f]+\b", re.I),  # hex addresses
    re.compile(r"\bpid[=:]?\s*\d+", re.I),  # PIDs
]


def normalize_error_signature(error: str) -> str:
    """Produce a stable, comparable signature from an error message.

    Strips variable parts (line numbers, paths, timestamps, etc.) so that
    two occurrences of the same *kind* of error compare equal.
    """
    sig = error.strip()
    for pat in _SIGNATURE_STRIP_PATTERNS:
        sig = pat.sub("", sig)
    # Collapse whitespace
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig


def classify_error(error: str) -> Literal["recoverable", "fatal"]:
    """Heuristically classify an error as recoverable or fatal.

    Recoverable errors are things like test failures, assertion errors,
    type mismatches — the agent can try again with a different approach.

    Fatal errors are things like missing credentials, network
    configuration issues, or resource exhaustion — no amount of retry
    will fix them.
    """
    lower = error.lower()
    fatal_patterns = [
        "missing credential",
        "authentication failed",
        "api key",
        "permission denied",
        "no such file or directory",
        "out of memory",
        "disk full",
        "enomem",
        "enospc",
        "network unreachable",
        "dns resolution failed",
        "connection refused",
        "rate limit",
        "quota exceeded",
    ]
    for pattern in fatal_patterns:
        if pattern in lower:
            return "fatal"
    return "recoverable"


# ── LoopEngine ───────────────────────────────────────────────────────────────


class LoopEngine:
    """Orchestrates loop iterations with termination, evolution, and auditing.

    Usage::

        engine = LoopEngine(config)
        # Each iteration:
        if not engine.should_continue():
            reason = engine.stop_reason()
        engine.begin_iteration()           # records start
        # ... run the turn ...
        engine.record_success(tokens=123)  # or engine.record_error("...")
        # After verifier:
        engine.check_goal_met(verifier_passed=True)
    """

    def __init__(self, config: LoopConfig) -> None:
        self._config = config
        self._state = LoopState(
            config=config,
            remaining=config.max_iterations,
            started_at=time.time(),
        )
        self._stop_reason: str | None = None
        self._current_record: LoopTurnRecord | None = None

    # ── Public API ───────────────────────────────────────────────────────

    @property
    def state(self) -> LoopState:
        return self._state

    @property
    def config(self) -> LoopConfig:
        return self._config

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def should_continue(self) -> bool:
        """Check all termination conditions. Returns True if loop should go on."""
        if self._state.paused:
            return False

        # 1. Goal met
        if self._state.goal_met:
            self._stop_reason = "goal_met"
            return False

        # 2. Max iterations
        if self._state.remaining <= 0:
            self._stop_reason = "max_iterations"
            return False

        # 3. Token budget exceeded
        if (
            self._config.max_total_tokens is not None
            and self._state.total_tokens_used >= self._config.max_total_tokens
        ):
            self._stop_reason = "token_budget"
            return False

        # 4. No-progress detected
        if self._state.consecutive_same_error >= self._config.no_progress_threshold:
            self._stop_reason = "no_progress"
            return False

        # 5. Fatal error
        if self._state.last_error is not None:
            last = self._state.turn_history[-1] if self._state.turn_history else None
            if last is not None and last.error_category == "fatal":
                self._stop_reason = "fatal_error"
                return False

        # 6. Max consecutive errors
        if self._state.consecutive_errors >= self._config.max_consecutive_errors:
            self._stop_reason = "max_errors"
            return False

        return True

    def begin_iteration(self) -> LoopTurnRecord:
        """Mark the start of a new iteration. Returns the turn record."""
        self._state.current_iteration += 1
        self._state.remaining -= 1

        prompt = self.get_effective_prompt()
        record = LoopTurnRecord(
            iteration=self._state.current_iteration,
            prompt=prompt,
            started_at=time.time(),
        )
        self._current_record = record
        return record

    def record_success(self, tokens: int = 0) -> None:
        """Record a successful iteration."""
        now = time.time()
        self._state.total_tokens_used += tokens
        self._state.consecutive_errors = 0
        self._state.consecutive_same_error = 0
        self._state.last_error = None
        self._state.last_error_signature = None

        if self._current_record is not None:
            self._current_record.completed_at = now
            self._current_record.success = True
            self._current_record.tokens_used = tokens
            self._state.turn_history.append(self._current_record)
            self._current_record = None

    def record_error(self, error: str, category: str | None = None) -> None:
        """Record a failed iteration."""
        now = time.time()
        self._state.consecutive_errors += 1

        if category is None:
            category = classify_error(error)

        signature = normalize_error_signature(error)
        if signature == self._state.last_error_signature:
            self._state.consecutive_same_error += 1
        else:
            self._state.consecutive_same_error = 1
        self._state.last_error = error
        self._state.last_error_signature = signature

        if self._current_record is not None:
            self._current_record.completed_at = now
            self._current_record.success = False
            self._current_record.error = error
            self._current_record.error_category = category
            self._state.turn_history.append(self._current_record)
            self._current_record = None

    def check_goal_met(self, verifier_passed: bool) -> bool:
        """Check if the goal is met after a verifier run. Returns True if met."""
        if verifier_passed and self._config.goal is not None:
            self._state.goal_met = True
            return True
        return False

    def get_effective_prompt(self) -> str:
        """Get the prompt for the current iteration, with evolution if enabled."""
        if not self._config.evolve_prompt or not self._state.turn_history:
            return self._config.prompt

        last = self._state.turn_history[-1]
        if last.success is True:
            return self._config.prompt

        parts = [self._config.prompt]
        parts.append(
            f"Previous attempt (iteration {last.iteration}) failed"
            + (f" with: {last.error}" if last.error else ".")
        )
        parts.append("Try a different approach.")
        return " ".join(parts)

    def stop(self, reason: str = "user_stop") -> None:
        """Manually stop the loop."""
        self._stop_reason = reason

    def pause(self) -> None:
        self._state.paused = True

    def resume(self) -> None:
        self._state.paused = False

    # ── Serialisation helpers ────────────────────────────────────────────

    def status_payload(self) -> dict[str, object]:
        """Build the SSE-compatible loop_status payload (backward-compatible)."""
        limit = self._config.max_iterations
        used = max(limit - self._state.remaining, 0)
        no_progress_warning = (
            self._state.consecutive_same_error
            >= self._config.no_progress_threshold - 1
            and self._state.consecutive_same_error > 0
        )

        # Serialise last N turn records for UI
        max_history = 10
        history = self._state.turn_history[-max_history:]
        turn_history_payload = [
            {
                "iteration": t.iteration,
                "success": t.success,
                "tokens_used": t.tokens_used,
                "duration_ms": (
                    int((t.completed_at - t.started_at) * 1000)
                    if t.completed_at
                    else None
                ),
                "error": t.error,
                "error_category": t.error_category,
            }
            for t in history
        ]

        return {
            # Original fields (backward compat)
            "prompt": self._config.prompt,
            "limit": limit,
            "remaining": self._state.remaining,
            "used": used,
            "paused": self._state.paused,
            # New fields
            "current_iteration": self._state.current_iteration,
            "total_tokens_used": self._state.total_tokens_used,
            "goal": self._config.goal,
            "goal_met": self._state.goal_met,
            "consecutive_errors": self._state.consecutive_errors,
            "no_progress_warning": no_progress_warning,
            "turn_history": turn_history_payload,
            "config": {
                "goal": self._config.goal,
                "evolve_prompt": self._config.evolve_prompt,
                "max_total_tokens": self._config.max_total_tokens,
                "no_progress_threshold": self._config.no_progress_threshold,
                "verify_command": self._config.verify_command,
                "max_consecutive_errors": self._config.max_consecutive_errors,
                "delay_between_iterations": self._config.delay_between_iterations,
            },
        }

    def turn_complete_payload(self, record: LoopTurnRecord) -> dict[str, object]:
        """Build the loop_turn_complete SSE payload."""
        return {
            "type": "loop_turn_complete",
            "iteration": record.iteration,
            "success": record.success,
            "tokens_used": record.tokens_used,
            "duration_ms": (
                int((record.completed_at - record.started_at) * 1000)
                if record.completed_at
                else None
            ),
            "error": record.error,
            "error_category": record.error_category,
        }

    def stopped_payload(self) -> dict[str, object]:
        """Build the loop_stopped SSE payload."""
        reason = self._stop_reason or "user_stop"
        total = self._state.current_iteration
        summaries = {
            "goal_met": f"Goal met after {total} iterations.",
            "max_iterations": f"Reached maximum of {total} iterations.",
            "token_budget": f"Token budget exhausted after {total} iterations ({self._state.total_tokens_used} tokens used).",
            "no_progress": f"No progress detected after {total} iterations — same error repeated {self._state.consecutive_same_error} times.",
            "fatal_error": f"Fatal error after {total} iterations: {self._state.last_error or 'unknown'}.",
            "max_errors": f"Too many consecutive errors ({self._state.consecutive_errors}) after {total} iterations.",
            "user_stop": f"Stopped by user after {total} iterations.",
        }
        return {
            "type": "loop_stopped",
            "reason": reason,
            "total_iterations": total,
            "total_tokens_used": self._state.total_tokens_used,
            "goal_met": self._state.goal_met,
            "summary": summaries.get(reason, f"Loop stopped ({reason})."),
        }
