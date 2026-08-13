"""Opt-in Language Server Protocol client manager."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin.shell import _scrubbed_env


@dataclass(frozen=True)
class LanguageServerSpec:
    language_id: str
    extensions: frozenset[str]
    commands: tuple[tuple[str, ...], ...]


SPECS: tuple[LanguageServerSpec, ...] = (
    LanguageServerSpec(
        "python",
        frozenset({".py", ".pyi", ".pyw"}),
        (
            ("basedpyright-langserver", "--stdio"),
            ("pyright-langserver", "--stdio"),
        ),
    ),
    LanguageServerSpec(
        "typescript",
        frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}),
        (("typescript-language-server", "--stdio"),),
    ),
    LanguageServerSpec("c", frozenset({".c", ".h", ".m"}), (("clangd",),)),
    LanguageServerSpec(
        "cpp",
        frozenset({".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".mm"}),
        (("clangd",),),
    ),
    LanguageServerSpec("java", frozenset({".java"}), (("jdtls",),)),
    LanguageServerSpec(
        "kotlin", frozenset({".kt", ".kts"}), (("kotlin-language-server", "--stdio"),)
    ),
    LanguageServerSpec(
        "csharp",
        frozenset({".cs"}),
        (("OmniSharp", "-lsp"), ("omnisharp", "-lsp")),
    ),
    LanguageServerSpec(
        "php",
        frozenset({".php", ".phtml"}),
        (("intelephense", "--stdio"), ("phpactor", "language-server")),
    ),
    LanguageServerSpec("swift", frozenset({".swift"}), (("sourcekit-lsp",),)),
    LanguageServerSpec(
        "dart", frozenset({".dart"}), (("dart", "language-server", "--protocol=lsp"),)
    ),
    LanguageServerSpec(
        "ruby", frozenset({".rb", ".rake", ".gemspec"}),
        (("ruby-lsp",), ("solargraph", "stdio")),
    ),
    LanguageServerSpec("lua", frozenset({".lua"}), (("lua-language-server",),)),
    LanguageServerSpec(
        "html", frozenset({".html", ".htm"}), (("vscode-html-language-server", "--stdio"),)
    ),
    LanguageServerSpec(
        "css",
        frozenset({".css", ".scss", ".sass", ".less"}),
        (("vscode-css-language-server", "--stdio"),),
    ),
    LanguageServerSpec(
        "json",
        frozenset({".json", ".jsonc", ".jsonl"}),
        (("vscode-json-language-server", "--stdio"),),
    ),
    LanguageServerSpec(
        "yaml", frozenset({".yaml", ".yml"}), (("yaml-language-server", "--stdio"),)
    ),
    LanguageServerSpec(
        "bash", frozenset({".sh", ".bash"}), (("bash-language-server", "start", "--stdio"),)
    ),
    LanguageServerSpec(
        "markdown",
        frozenset({".md", ".markdown", ".mdx"}),
        (("marksman", "server"),),
    ),
    LanguageServerSpec("toml", frozenset({".toml"}), (("taplo", "lsp", "stdio"),)),
    LanguageServerSpec("vue", frozenset({".vue"}), (("vue-language-server", "--stdio"),)),
    LanguageServerSpec("svelte", frozenset({".svelte"}), (("svelteserver", "--stdio"),)),
    LanguageServerSpec("go", frozenset({".go"}), (("gopls",),)),
    LanguageServerSpec("rust", frozenset({".rs"}), (("rust-analyzer",),)),
)


class LanguageServerUnavailable(RuntimeError):
    """No configured language-server binary is available."""


class LanguageServerClient:
    """One JSON-RPC/LSP subprocess scoped to a workspace and language."""

    def __init__(
        self,
        workspace: Path,
        spec: LanguageServerSpec,
        command: tuple[str, ...],
    ) -> None:
        self.workspace = workspace.resolve()
        self.spec = spec
        self.command = command
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 0
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        # Track the document text rather than only its mtime.  The coding
        # editor can send an unsaved buffer, so mtime is not sufficient to
        # decide whether a didChange notification is required.
        self._versions: dict[str, tuple[int, str]] = {}
        self._diagnostics: dict[str, list[dict[str, Any]]] = {}
        self._diagnostic_events: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        async with self._start_lock:
            if self._process is not None and self._process.returncode is None:
                return
            sandbox = get_sandbox()
            self._process = await asyncio.create_subprocess_exec(
                self.command[0],
                *self.command[1:],
                cwd=str(self.workspace),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
            )
            self._reader_task = asyncio.create_task(
                self._read_messages(),
                name=f"lsp:{self.spec.language_id}:{self.workspace.name}",
            )
            await self.request(
                "initialize",
                {
                    "processId": None,
                    "rootUri": self.workspace.as_uri(),
                    "capabilities": {
                        "textDocument": {
                            "publishDiagnostics": {
                                "relatedInformation": True,
                                "versionSupport": True,
                            }
                        },
                        "workspace": {"configuration": False},
                    },
                    "workspaceFolders": [
                        {"uri": self.workspace.as_uri(), "name": self.workspace.name}
                    ],
                },
                ensure_started=False,
                timeout=20,
            )
            await self.notify("initialized", {}, ensure_started=False)
            logger.info(
                "lsp_started language={} workspace={} command={}",
                self.spec.language_id,
                self.workspace,
                self.command[0],
            )

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        ensure_started: bool = True,
        timeout: float = 15,
    ) -> Any:
        if ensure_started:
            await self.start()
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def notify(
        self,
        method: str,
        params: dict[str, Any],
        *,
        ensure_started: bool = True,
    ) -> None:
        if ensure_started:
            await self.start()
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def sync_document(
        self, path: Path, content: str | None = None
    ) -> tuple[str, bool]:
        await self.start()
        resolved = path.resolve()
        uri = resolved.as_uri()
        if content is None:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        fingerprint = hashlib.sha1(content.encode("utf-8")).hexdigest()
        previous = self._versions.get(uri)
        event = self._diagnostic_events.setdefault(uri, asyncio.Event())
        changed = previous is None or previous[1] != fingerprint
        if changed:
            event.clear()
        if previous is None:
            version = 1
            await self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": self.spec.language_id,
                        "version": version,
                        "text": content,
                    }
                },
                ensure_started=False,
            )
        elif previous[1] != fingerprint:
            version = previous[0] + 1
            await self.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": content}],
                },
                ensure_started=False,
            )
        else:
            version = previous[0]
        self._versions[uri] = (version, fingerprint)
        return uri, changed

    async def diagnostics(
        self, path: Path, content: str | None = None
    ) -> list[dict[str, Any]]:
        uri, changed = await self.sync_document(path, content)
        event = self._diagnostic_events.setdefault(uri, asyncio.Event())
        if changed:
            try:
                await asyncio.wait_for(event.wait(), timeout=2)
            except TimeoutError:
                pass
        return list(self._diagnostics.get(uri, []))

    async def definition(
        self, path: Path, line: int, column: int
    ) -> list[dict[str, Any]]:
        uri, _ = await self.sync_document(path)
        result = await self.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": column - 1},
            },
        )
        return _locations(result)

    async def references(
        self,
        path: Path,
        line: int,
        column: int,
        *,
        include_declaration: bool,
    ) -> list[dict[str, Any]]:
        uri, _ = await self.sync_document(path)
        result = await self.request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": column - 1},
                "context": {"includeDeclaration": include_declaration},
            },
        )
        return _locations(result)

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            await self.request("shutdown", {}, ensure_started=False, timeout=5)
            await self.notify("exit", {}, ensure_started=False)
        except Exception:  # noqa: BLE001
            pass
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
        if self._reader_task is not None:
            self._reader_task.cancel()
        self._process = None

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise LanguageServerUnavailable("Language server is not running.")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        async with self._write_lock:
            process.stdin.write(frame)
            await process.stdin.drain()

    async def _read_messages(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                header = await process.stdout.readuntil(b"\r\n\r\n")
                content_length = _content_length(header)
                body = await process.stdout.readexactly(content_length)
                message = json.loads(body)
                request_id = message.get("id")
                if request_id is not None and request_id in self._pending:
                    future = self._pending[request_id]
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"])))
                    else:
                        future.set_result(message.get("result"))
                    continue
                if message.get("method") == "textDocument/publishDiagnostics":
                    params = message.get("params") or {}
                    uri = str(params.get("uri") or "")
                    diagnostics = params.get("diagnostics") or []
                    self._diagnostics[uri] = (
                        diagnostics if isinstance(diagnostics, list) else []
                    )
                    self._diagnostic_events.setdefault(uri, asyncio.Event()).set()
        except (
            asyncio.CancelledError,
            asyncio.IncompleteReadError,
            json.JSONDecodeError,
            ValueError,
        ):
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(
                        LanguageServerUnavailable("Language server exited.")
                    )


_clients: dict[tuple[Path, str], LanguageServerClient] = {}
_clients_lock = asyncio.Lock()


def language_server_spec(path: Path) -> LanguageServerSpec | None:
    """Return the configured server mapping for a source path."""
    return next(
        (item for item in SPECS if path.suffix.lower() in item.extensions), None
    )


async def get_language_server(workspace: Path, path: Path) -> LanguageServerClient:
    spec = language_server_spec(path)
    if spec is None:
        raise LanguageServerUnavailable(
            f"No language-server mapping for extension '{path.suffix}'."
        )
    command = next(
        (
            candidate
            for candidate in spec.commands
            if shutil.which(candidate[0]) is not None
        ),
        None,
    )
    if command is None:
        names = ", ".join(candidate[0] for candidate in spec.commands)
        raise LanguageServerUnavailable(
            f"No {spec.language_id} language server found. Install one of: {names}."
        )
    key = (workspace.resolve(), spec.language_id)
    async with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = LanguageServerClient(workspace, spec, command)
            _clients[key] = client
    await client.start()
    return client


async def close_language_servers() -> None:
    clients = list(_clients.values())
    _clients.clear()
    await asyncio.gather(
        *(client.close() for client in clients), return_exceptions=True
    )


def _content_length(header: bytes) -> int:
    for raw_line in header.decode("ascii", errors="replace").split("\r\n"):
        name, separator, value = raw_line.partition(":")
        if separator and name.casefold() == "content-length":
            return int(value.strip())
    raise ValueError("LSP frame is missing Content-Length.")


def _locations(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    return (
        [item for item in result if isinstance(item, dict)]
        if isinstance(result, list)
        else []
    )
