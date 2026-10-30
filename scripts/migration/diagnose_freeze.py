"""Measure v3.1.1 health latency under isolated diagnostic workloads."""

from __future__ import annotations

import argparse
import concurrent.futures
import http.server
import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]


class Provider(http.server.BaseHTTPRequestHandler):
    shell_requested = False
    shell_emitted = threading.Event()
    observed_tools: list[list[str]] = []

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps(
            {"object": "list", "data": [{"id": "gpt-4o", "object": "model"}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not payload.get("stream", False):
            if self.path.endswith("/responses"):
                reply = {
                    "id": "resp_diag",
                    "object": "response",
                    "model": "gpt-4o",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_diag",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Diagnostic",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                }
            else:
                reply = {
                    "id": "diag",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Diagnostic"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            body = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        names = [
            str(t.get("name") or t.get("function", {}).get("name"))
            for t in payload.get("tools", [])
        ]
        self.observed_tools.append(names)
        use_shell = (
            self.shell_requested
            and not self.shell_emitted.is_set()
            and "shell" in names
        )
        command = f'"{sys.executable}" -c "import time; time.sleep(12)"'
        args = json.dumps(
            {"command": command, "description": "Run the diagnostic wait"}
        )
        if self.path.endswith("/responses"):
            events = [{"type": "response.created", "response": {"id": "resp_diag"}}]
            if use_shell:
                events.extend(
                    [
                        {
                            "type": "response.output_item.added",
                            "item": {
                                "id": "fc_diag",
                                "call_id": "call_diag",
                                "type": "function_call",
                                "name": "shell",
                            },
                        },
                        {
                            "type": "response.function_call_arguments.done",
                            "item_id": "fc_diag",
                            "arguments": args,
                        },
                    ]
                )
            else:
                events.extend(
                    [
                        {
                            "type": "response.output_text.delta",
                            "delta": "Diagnostic complete.",
                        },
                        {"type": "response.output_text.done"},
                    ]
                )
            events.append(
                {"type": "response.completed", "response": {"id": "resp_diag"}}
            )
            body = (
                "".join("data: " + json.dumps(event) + "\n\n" for event in events)
                + "data: [DONE]\n\n"
            ).encode()
        else:
            delta = (
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_diag",
                            "type": "function",
                            "function": {"name": "shell", "arguments": args},
                        }
                    ]
                }
                if use_shell
                else {"content": "Diagnostic complete."}
            )
            chunk = {
                "id": "diag",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": "tool_calls" if use_shell else "stop",
                    }
                ],
            }
            body = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if use_shell:
            self.shell_emitted.set()


class Backend:
    def __init__(self, temp: Path, provider_port: int, repo: Path, source_root: Path):
        self.log: list[str] = []
        self.handshake: queue.Queue[dict] = queue.Queue()
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in {
                "PATH",
                "PATHEXT",
                "SYSTEMROOT",
                "SYSTEMDRIVE",
                "WINDIR",
                "COMSPEC",
                "TEMP",
                "TMP",
                "LANG",
            }
        }
        env.update(
            {
                "USERPROFILE": str(temp / "home"),
                "HOME": str(temp / "home"),
                "APPDATA": str(temp / "home" / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(temp / "home" / "AppData" / "Local"),
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "APP_ENV": "production",
                "OPENAI_API_KEY": "diagnostic-only",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{provider_port}/v1",
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": repo.as_posix(),
                "EVOFLUX_MODEL_REGISTRY_REFRESH": "false",
            }
        )
        for name in ("DATA", "CONFIG", "STATE", "CACHE", "WORKSPACE", "WIKI"):
            env[f"EVOFLUX_{name}_DIR"] = str(temp / name.lower())
        config = temp / "config" / "agents"
        for sub in (Path(), Path("coding")):
            dst = config / sub
            dst.mkdir(parents=True, exist_ok=True)
            for source in (source_root / "seed" / "agents" / sub).glob("*.md"):
                text = (
                    source.read_text(encoding="utf-8")
                    .replace("__PROVIDER_MODEL__", "openai:gpt-4o")
                    .replace(
                        "thinking_level: low",
                        "thinking_level: none\nresponses_api: false",
                    )
                )
                (dst / source.name).write_text(text, encoding="utf-8")
        self.process = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "-m",
                "app.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--handshake",
                "--generate-token",
            ],
            cwd=source_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )

        def pump() -> None:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                if line.startswith("EVOFLUX_HANDSHAKE "):
                    self.handshake.put(
                        json.loads(line.removeprefix("EVOFLUX_HANDSHAKE "))
                    )
                else:
                    self.log.append(line)

        threading.Thread(target=pump, daemon=True).start()
        try:
            info = self.handshake.get(timeout=100)
        except queue.Empty as exc:
            self.stop()
            raise RuntimeError(
                "backend handshake timeout; check isolated server logs"
            ) from exc
        self.pid = int(info["pid"])
        self.url = f"http://127.0.0.1:{info['port']}"
        self.client = httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {info['token']}"},
            timeout=90,
            trust_env=False,
        )

    def stop(self) -> None:
        if hasattr(self, "client"):
            self.client.close()
        if self.process.poll() is None:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
                if result.returncode and self.process.poll() is None:
                    raise RuntimeError("failed to terminate backend process tree")
            else:
                import signal

                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, path, **kwargs)
        if response.is_error:
            raise RuntimeError(
                f"HTTP {response.status_code} for {path}: {response.text[:500]}"
            )
        return response


class Probe:
    def __init__(self, backend: Backend, label: str, output: Path, pyspy: str):
        self.backend, self.label, self.output, self.pyspy = (
            backend,
            label,
            output,
            pyspy,
        )
        self.values: list[float] = []
        self.errors: list[str] = []
        self.done = threading.Event()
        self.dump_count = 0
        self.dump_threads: list[threading.Timer] = []
        self.dump_lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def dump(self) -> None:
        with self.dump_lock:
            self.dump_count += 1
            number = self.dump_count
        path = self.output / f"{self.label}-stall-{number}.txt"
        try:
            with path.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    [self.pyspy, "dump", "--pid", str(self.backend.pid)],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                    check=False,
                )
            if result.returncode:
                self.errors.append(f"py-spy failed: {result.returncode}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.errors.append(f"py-spy failed: {exc}")

    def run(self) -> None:
        with httpx.Client(
            base_url=self.backend.url, timeout=30, trust_env=False
        ) as client:
            while not self.done.is_set():
                started = time.monotonic()
                timer = threading.Timer(1, self.dump)
                self.dump_threads.append(timer)
                timer.start()
                try:
                    response = client.get("/api/health/live")
                    response.raise_for_status()
                except Exception as exc:
                    self.errors.append(f"{type(exc).__name__}: {exc}")
                finally:
                    timer.cancel()
                    self.values.append((time.monotonic() - started) * 1000)
                self.done.wait(max(0, 0.05 - (time.monotonic() - started)))

    def __enter__(self) -> Probe:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.done.set()
        self.thread.join(timeout=35)
        if self.thread.is_alive():
            raise RuntimeError("health probe did not stop")
        for timer in self.dump_threads:
            timer.join(timeout=35)
            if timer.is_alive():
                self.errors.append("py-spy capture did not finish")

    def summary(self) -> dict:
        values = sorted(self.values)
        if not values:
            raise RuntimeError("no health probes completed")
        return {
            "scenario": self.label,
            "samples": len(values),
            "max_ms": round(values[-1], 2),
            "p99_ms": round(values[max(0, math.ceil(len(values) * 0.99) - 1)], 2),
            "stall_dumps": self.dump_count,
            "errors": self.errors,
        }


def large_repo_open(backend: Backend, repo: Path) -> None:
    project = backend.request(
        "POST",
        "/api/team/projects",
        json={"name": "Freeze diagnostic", "workspace_paths": [str(repo)]},
    ).json()
    workspace = {"workspace": str(repo)}
    connected = threading.Event()
    observed = threading.Event()

    def watch() -> None:
        with httpx.Client(
            base_url=backend.url,
            headers=backend.client.headers,
            timeout=30,
            trust_env=False,
        ) as client:
            with client.stream(
                "GET", "/api/team/workspace/watch", params=workspace
            ) as response:
                response.raise_for_status()
                connected.set()
                for line in response.iter_lines():
                    if line.startswith("event: fs_change"):
                        observed.set()
                        return

    with (
        tempfile.TemporaryDirectory(prefix="evofreeze-write-", dir=repo) as folder,
        concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool,
    ):
        watcher = pool.submit(watch)
        if not connected.wait(15):
            raise RuntimeError("workspace watcher failed to connect")

        def writes() -> None:
            for i in range(2000):
                (Path(folder) / f"{i:04d}.txt").write_text(
                    "diagnostic\n", encoding="utf-8"
                )

        jobs = [
            pool.submit(
                backend.request,
                "GET",
                "/api/team/workspace/files/list",
                params=workspace,
            ),
            pool.submit(
                backend.request,
                "GET",
                "/api/team/workspace/git/changes",
                params=workspace,
            ),
            pool.submit(
                backend.request,
                "GET",
                "/api/team/workspace/git-diff/view",
                params=workspace,
            ),
            pool.submit(
                backend.request,
                "POST",
                "/api/team/workspace/search-everywhere",
                params=workspace,
                json={"query": "editor", "limit": 50},
            ),
            pool.submit(writes),
        ]
        for job in jobs:
            job.result(timeout=90)
        if not observed.wait(20):
            raise RuntimeError("workspace watcher did not report file writes")
        watcher.result(timeout=10)
    print(
        json.dumps(
            {"project_id": project["id"], "repository": str(repo), "writes": 2000}
        ),
        flush=True,
    )


def history_reads(backend: Backend) -> None:
    session = backend.request(
        "POST", "/api/team/sessions/resolve", json={"mode": "work", "create": True}
    ).json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = [
            pool.submit(backend.request, "GET", f"/api/team/{session['id']}/history")
            for _ in range(20)
        ]
        for future in futures:
            future.result(timeout=60)


def mcp_never_answers(backend: Backend, temp: Path) -> None:
    marker = temp / "mcp-started"
    code = f"import pathlib,time; pathlib.Path({str(marker)!r}).write_text('started'); time.sleep(30)"
    result = backend.request(
        "POST",
        "/api/mcp/servers",
        json={
            "name": "freeze-diagnostic",
            "server": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-c", code],
            },
        },
    ).json()
    if not marker.exists():
        raise RuntimeError("nonresponsive MCP process did not start")
    if result.get("state") == "ready":
        raise RuntimeError("nonresponsive MCP unexpectedly became ready")


def long_shell_tool(backend: Backend) -> None:
    Provider.shell_requested = True
    Provider.shell_emitted.clear()
    try:
        response = backend.request(
            "POST",
            "/api/team/chat",
            data={
                "message": "Use the shell tool to execute the diagnostic wait.",
                "mode": "work",
                "permission_mode": "bypass",
            },
        )
        if not Provider.shell_emitted.wait(30):
            raise RuntimeError("mock provider did not receive a shell-capable request")
        session_id = response.json()["session_id"]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            result = backend.client.get(f"/api/team/{session_id}/history")
            if result.status_code == 200:
                messages = result.json()["lead"]["messages"]
                for message in messages:
                    if message.get("role") == "tool" and message.get("name") == "shell":
                        extra = message.get("extra") or {}
                        if (
                            extra.get("status") != "succeeded"
                            or extra.get("duration_ms", 0) < 10000
                        ):
                            raise RuntimeError(
                                "shell tool did not complete the requested long wait"
                            )
                        return
            time.sleep(0.2)
        raise RuntimeError("shell tool result was not persisted before timeout")
    finally:
        Provider.shell_requested = False


def make_large_pdf(path: Path, pages: int = 400) -> None:
    # Each page has a text layer, so this exercises PDFium text extraction.
    text = "Diagnostic PDF text for responsiveness testing. " * 3
    commands = ["BT /F1 10 Tf 36 750 Td"]
    for _ in range(55):
        commands.append(f"({text}) Tj 0 -12 Td")
    commands.append("ET")
    content = "\n".join(commands).encode("ascii")
    page_ids = [4 + 2 * i for i in range(pages)]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {pages} /Kids [".encode()
        + b" ".join(f"{n} 0 R".encode() for n in page_ids)
        + b"] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for page_id in page_ids:
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode()
            + content
            + b"\nendstream"
        )
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(data)


def large_pdf_intake(backend: Backend, temp: Path) -> None:
    path = temp / "large.pdf"
    make_large_pdf(path)
    with path.open("rb") as stream:
        response = backend.request(
            "POST",
            "/api/team/chat",
            data={"message": "Read the attached diagnostic PDF.", "mode": "work"},
            files={"files": ("large.pdf", stream, "application/pdf")},
        )
    if response.json().get("status") != "accepted":
        raise RuntimeError("PDF intake did not accept the document")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, required=True, help="Disposable large Git checkout"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Directory for summaries and stack dumps",
    )
    parser.add_argument("--py-spy", default="py-spy")
    parser.add_argument(
        "--v3-source", type=Path, default=ROOT, help="Clean v3.1.1 source checkout"
    )
    parser.add_argument(
        "--scenario",
        choices=(
            "large_repo_open",
            "long_shell_tool",
            "history_reads",
            "mcp_never_answers",
            "large_pdf_intake",
        ),
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    source_root = args.v3_source.resolve()
    checked = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "diff",
            "--quiet",
            "8fd844d5",
            "--",
            "app",
            "seed",
            "pyproject.toml",
            "uv.lock",
        ],
        check=False,
    )
    if checked.returncode:
        parser.error("--v3-source must match v3.1.1 in app, seed and dependencies")
    untracked = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "app",
            "seed",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    if untracked.stdout.strip() or (source_root / ".env").exists():
        parser.error("--v3-source must not contain untracked app/seed files or a .env")
    if not (repo / ".git").exists():
        parser.error("--repo must be a Git checkout")
    args.output.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix="evofreeze-") as folder:
            temp = Path(folder)
            backend = Backend(temp, server.server_port, repo, source_root)
            try:
                scenarios = (
                    ("large_repo_open", lambda: large_repo_open(backend, repo)),
                    ("long_shell_tool", lambda: long_shell_tool(backend)),
                    ("history_reads", lambda: history_reads(backend)),
                    ("mcp_never_answers", lambda: mcp_never_answers(backend, temp)),
                    ("large_pdf_intake", lambda: large_pdf_intake(backend, temp)),
                )
                for label, action in scenarios:
                    if args.scenario and label != args.scenario:
                        continue
                    probe = Probe(backend, label, args.output, args.py_spy)
                    error = None
                    try:
                        with probe:
                            action()
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                    result = probe.summary()
                    result["workload_error"] = error
                    results.append(result)
                    print(json.dumps(result), flush=True)
            finally:
                backend.stop()
    finally:
        server.shutdown()
        server.server_close()
    (args.output / "summary.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    return 1 if any(r["workload_error"] or r["errors"] for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
