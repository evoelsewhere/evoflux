"""Compatibility import for the shared rolling live edit budget."""

from __future__ import annotations

from app.remote.live_budget import RollingEditBudget

IMessageLiveBudget = RollingEditBudget

__all__ = ["IMessageLiveBudget", "RollingEditBudget"]
