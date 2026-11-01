"""Materialise the fixture workspaces and run cases through a tool driver."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PARITY = ROOT / "server" / "crates" / "area-tools" / "tests" / "parity"
PLATFORM = "windows" if sys.platform == "win32" else "posix"

Driver = Callable[[Path, list[dict[str, Any]]], list[dict[str, Any]]]


class Workspace:
    """One materialised fixture: ``<root>/ws`` and the ``<root>/outside`` beside it."""

    def __init__(self, root: Path, fixture: dict[str, Any], outside: dict[str, str]):
        self.root = root.resolve()
        self.ws = self.root / "ws"
        self.out = self.root / "outside"
        self.links_ok = True
        self.ws.mkdir(parents=True)
        self.out.mkdir()
        for name, text in outside.items():
            (self.out / name).write_text(text, encoding="utf-8", newline="")
        for name, entry in fixture["files"].items():
            path = self.ws / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if "b64" in entry:
                path.write_bytes(base64.b64decode(entry["b64"]))
            else:
                path.write_bytes(entry["text"].encode("utf-8"))
            if "mtime" in entry:
                os.utime(path, (entry["mtime"], entry["mtime"]))
        for name in fixture["dirs"]:
            (self.ws / name).mkdir(parents=True, exist_ok=True)
        for link in fixture["links"]:
            self.links_ok = self._link(link) and self.links_ok

    def _link(self, link: dict[str, Any]) -> bool:
        target = Path(self.substitute(link["target"]))
        path = self.ws / link["path"]
        try:
            os.symlink(target, path, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            pass
        if sys.platform == "win32":
            made = subprocess.run(
                ["cmd", "/C", "mklink", "/J", str(path), str(target)],
                capture_output=True,
                check=False,
            )
            return made.returncode == 0
        return False

    def substitute(self, text: str) -> str:
        return text.replace("<WS>", str(self.ws)).replace("<OUT>", str(self.out))

    def args(self, args: dict[str, Any]) -> dict[str, Any]:
        return json.loads(self.substitute_json(args))

    def substitute_json(self, value: Any) -> str:
        # Substitute inside the JSON text so nested values are covered, with
        # backslashes escaped the way JSON writes them.
        text = json.dumps(value, ensure_ascii=False)
        return text.replace("<WS>", json.dumps(str(self.ws))[1:-1]).replace(
            "<OUT>", json.dumps(str(self.out))[1:-1]
        )

    def normalise(self, content: str, *, slashes: bool, drive: bool = False) -> str:
        for real, token in (
            (self.out, "<OUT>"),
            (self.ws, "<WS>"),
            (self.root, "<ROOT>"),
        ):
            text = str(real)
            for variant in (text.replace("\\", "\\\\"), text, text.replace("\\", "/")):
                content = content.replace(variant, token)
        if slashes:
            content = content.replace("\\", "/")
        if drive and self.ws.drive:
            # A path with a root but no drive takes the workspace's drive.
            content = content.replace(self.ws.drive + "/", "<DRIVE>/")
        return content


def load_cases() -> dict[str, Any]:
    return json.loads((PARITY / "cases.json").read_text(encoding="utf-8"))


def applicable(case: dict[str, Any]) -> bool:
    return case.get("only_os") in (None, PLATFORM)


def run_all(
    data: dict[str, Any], driver: Driver, tmp: Path
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Run every applicable case; returns ``(results by id, skipped ids)``."""
    results: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for name, fixture in data["fixtures"].items():
        workspace = Workspace(tmp / name, fixture, data["outside"])
        cases = [
            c
            for c in data["cases"]
            if c.get("fixture", "main") == name and applicable(c)
        ]
        if not workspace.links_ok:
            skipped += [c["id"] for c in cases if fixture["links"]]
            cases = [c for c in cases if not fixture["links"]]
        outputs = driver(
            workspace.ws,
            [{"tool": c["tool"], "args": workspace.args(c["args"])} for c in cases],
        )
        for case, output in zip(cases, outputs, strict=True):
            content = workspace.normalise(
                output["content"],
                slashes=bool(case.get("normalize")),
                drive=bool(case.get("normalize_drive")),
            )
            prefix = case.get("prefix_only")
            if prefix is not None:
                assert content.startswith(prefix), (case["id"], content)
                content = prefix
            results[case["id"]] = {"content": content, "is_error": output["is_error"]}
    return results, skipped


def python_driver(workspace: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request = json.dumps({"workspace": str(workspace), "cases": cases})
    done = subprocess.run(
        [sys.executable, str(HERE / "py_driver.py")],
        input=request.encode("utf-8"),
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(done.stdout.decode("utf-8"))


def rust_driver(workspace: Path, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request = json.dumps({"workspace": str(workspace), "cases": cases})
    done = subprocess.run(
        [
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            str(ROOT / "server" / "Cargo.toml"),
            "-p",
            "evoflux-area-tools",
            "--example",
            "run_cases",
        ],
        input=request.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(done.stdout.decode("utf-8"))
