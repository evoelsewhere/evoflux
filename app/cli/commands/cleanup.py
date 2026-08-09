"""``evoflux cleanup`` — prune generated artifacts."""

from __future__ import annotations

import argparse
import asyncio

from app.cli.ui import _bold, _cyan, _dim, _green, _yellow
from app.core.db import get_session
from app.services.artifact_cleanup import cleanup_generated_artifacts


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


async def _run_cleanup(args: argparse.Namespace) -> None:
    async for db in get_session():
        result = await cleanup_generated_artifacts(
            db,
            older_than_days=args.older_than_days,
            dry_run=args.dry_run,
        )
        break

    mode = "dry run" if result.dry_run else "deleted"
    print(f"  {_bold(_cyan('Generated artifact cleanup'))} ({mode})")
    print(f"  {_dim('Candidates:')} {len(result.candidates)}")
    print(f"  {_dim('Total:')}      {_format_bytes(result.total_bytes)}")

    for candidate in result.candidates[: args.limit]:
        print(
            f"  - {_format_bytes(candidate.bytes):>9}  "
            f"{candidate.reason}: {candidate.path}"
        )
    if len(result.candidates) > args.limit:
        print(f"  {_dim(f'... {len(result.candidates) - args.limit} more')}")

    if result.dry_run:
        print(
            f"  {_yellow('No files deleted.')} Re-run with {_bold('--apply')} to delete."
        )
    else:
        print(f"  {_green('Deleted')} {len(result.deleted)} paths.")


def cmd_cleanup(args: argparse.Namespace) -> None:
    """Run generated artifact cleanup."""
    asyncio.run(_run_cleanup(args))
