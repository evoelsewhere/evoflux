"""Deterministic line-delimited JSON-RPC server for protocol-level iMessage tests."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


FEATURES = ["messages.after", "send", "reply", "attachments"]
MESSAGES: list[dict[str, object]] = []


def load_state() -> None:
    state_path = os.environ.get("MOCK_IMSG_STATE")
    if not state_path:
        return
    path = Path(state_path)
    if path.exists():
        MESSAGES.extend(json.loads(path.read_text(encoding="utf-8")))


def save_state() -> None:
    state_path = os.environ.get("MOCK_IMSG_STATE")
    if state_path:
        Path(state_path).write_text(json.dumps(MESSAGES), encoding="utf-8")


def response(request_id: object, result: dict[str, object]) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n"
    )
    sys.stdout.flush()


def main() -> None:
    load_state()
    for line in sys.stdin:
        request = json.loads(line)
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            response(request_id, {"ready": True, "protocol_version": 1})
        elif method == "status":
            response(request_id, {"ready": True, "features": FEATURES})
        elif method == "messages.after":
            # Rows are 1-indexed by position, matching the real RPC's
            # ROWID-ordered, exclusive `since_rowid` cursor closely enough
            # for a protocol-shape test: no persisted numeric id is needed
            # since this mock never reorders or deletes `MESSAGES`.
            since_rowid = int(params.get("since_rowid") or 0)
            matched = [
                (index, item)
                for index, item in enumerate(MESSAGES, start=1)
                if index > since_rowid
            ]
            next_rowid = matched[-1][0] if matched else since_rowid
            response(
                request_id,
                {
                    "messages": [item for _, item in matched],
                    "next_rowid": next_rowid,
                    "has_more": False,
                },
            )
        elif method == "send":
            record = {
                "guid": f"mock-{len(MESSAGES) + 1}",
                "chat_identifier": params.get("chat_identifier"),
                "text": params.get("text", ""),
                "reply_to": params.get("reply_to"),
                "attachments": params.get("attachments", []),
                "date": datetime.now(UTC).isoformat(),
            }
            MESSAGES.append(record)
            save_state()
            response(request_id, record)
        else:
            response(request_id, {"error": f"unsupported method: {method}"})


if __name__ == "__main__":
    main()
