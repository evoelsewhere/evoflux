"""Windows AppContainer + Job Object backend for declarative plugin hooks."""

from __future__ import annotations

import asyncio
import ctypes
import os
import shutil
import subprocess
import uuid
from ctypes import wintypes
from pathlib import Path

from app.agent.plugins.hook_runner import (
    HOOK_ISOLATION_PROFILE,
    HookExecutionError,
    HookExecutionLimits,
    HookIsolationUnavailable,
    IsolatedProcess,
)

CREATE_SUSPENDED = 0x4
CREATE_UNICODE_ENVIRONMENT = 0x400
EXTENDED_STARTUPINFO_PRESENT = 0x80000
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x20002
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x20009
STARTF_USESTDHANDLES = 0x100
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x2
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class _HookLaunchCancelled(Exception):
    """Internal signal used to unwind native setup after cancellation."""


class SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", wintypes.LPVOID),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPBYTE),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", wintypes.LPVOID)]


class ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def kernel32():
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    lib.CloseHandle.restype = wintypes.BOOL
    lib.LocalFree.argtypes = [wintypes.LPVOID]
    lib.LocalFree.restype = wintypes.LPVOID
    lib.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(SecurityAttributes),
        wintypes.DWORD,
    ]
    lib.SetHandleInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    lib.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    lib.CreateJobObjectW.restype = wintypes.HANDLE
    lib.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    lib.SetInformationJobObject.restype = wintypes.BOOL
    lib.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.LPVOID,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.UpdateProcThreadAttribute.restype = wintypes.BOOL
    lib.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        ctypes.POINTER(ProcessInformation),
    ]
    lib.CreateProcessW.restype = wintypes.BOOL
    lib.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    lib.AssignProcessToJobObject.restype = wintypes.BOOL
    lib.ResumeThread.argtypes = [wintypes.HANDLE]
    lib.ResumeThread.restype = wintypes.DWORD
    lib.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    lib.TerminateJobObject.restype = wintypes.BOOL
    lib.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    lib.TerminateProcess.restype = wintypes.BOOL
    lib.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    lib.WaitForSingleObject.restype = wintypes.DWORD
    lib.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    lib.GetExitCodeProcess.restype = wintypes.BOOL
    lib.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    lib.ReadFile.restype = wintypes.BOOL
    lib.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    lib.WriteFile.restype = wintypes.BOOL
    lib.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    lib.DeleteProcThreadAttributeList.restype = None
    return lib


def _delete_appcontainer_profile(name: str) -> None:
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile(name)


def _err(where: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), where)


def _close(handle: int | None) -> None:
    if handle:
        kernel32().CloseHandle(wintypes.HANDLE(handle))


def _restrict_tree(path: Path, sid: int, *, writable: bool) -> None:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    sid_text = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
        raise _err("format AppContainer SID")
    try:
        icacls = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / "icacls.exe"
        )

        def grant(target: Path, ace: str, recursive: bool = False) -> None:
            args = [
                str(icacls),
                str(target),
                "/grant",
                f"*{sid_text.value}:{ace}",
                "/Q",
            ]
            if recursive:
                args.append("/T")
            completed = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode:
                raise HookIsolationUnavailable("could not apply AppContainer file ACL")

        # The Windows traverse privilege resolves ancestors without granting
        # read access. Add an explicit traverse ACE only to the private temp
        # parent; never alter ACLs on the user's profile or other shared dirs.
        grant(path.parent, "(X)")
        grant(path, "(OI)(CI)(F)" if writable else "(OI)(CI)(RX)", True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HookIsolationUnavailable("could not apply AppContainer file ACL") from exc
    finally:
        kernel32().LocalFree(sid_text)


def _new_pipe(child_reads: bool) -> tuple[int, int]:
    lib = kernel32()
    security = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
    read, write = wintypes.HANDLE(), wintypes.HANDLE()
    if not lib.CreatePipe(
        ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0
    ):
        raise _err("create hook pipe")
    child, parent = (
        (read.value, write.value) if child_reads else (write.value, read.value)
    )
    if child is None or parent is None:
        _close(child)
        _close(parent)
        raise HookIsolationUnavailable("could not create hook pipe handles")
    if not lib.SetHandleInformation(wintypes.HANDLE(parent), 1, 0):
        _close(child)
        _close(parent)
        raise _err("restrict hook pipe inheritance")
    return int(child), int(parent)


def _new_job(limits: HookExecutionLimits) -> int:
    lib = kernel32()
    job = lib.CreateJobObjectW(None, None)
    if not job:
        raise _err("create hook Job Object")
    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_PROCESS_TIME
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    info.BasicLimitInformation.ActiveProcessLimit = limits.max_processes
    info.BasicLimitInformation.PerProcessUserTimeLimit = (
        limits.cpu_time_seconds * 10_000_000
    )
    info.ProcessMemoryLimit = limits.memory_bytes
    if not lib.SetInformationJobObject(
        job,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        lib.CloseHandle(job)
        raise _err("apply hook Job Object limits")
    return int(job)


class WindowsProcess(IsolatedProcess):
    def __init__(
        self,
        process: int,
        job: int,
        stdout: int,
        stdin: int,
        profile: str,
        profile_storage: Path,
        output_limit: int,
    ) -> None:
        self.process, self.job, self.stdout, self.stdin = process, job, stdout, stdin
        self.profile, self.profile_storage = profile, profile_storage
        self.output_limit = output_limit
        self.closed = False

    def _read(self) -> bytes:
        lib, result = kernel32(), bytearray()
        buffer = ctypes.create_string_buffer(8192)
        while True:
            count = wintypes.DWORD()
            if not lib.ReadFile(
                self.stdout, buffer, len(buffer), ctypes.byref(count), None
            ):
                if ctypes.get_last_error() in {109, 38}:
                    break
                raise _err("read hook output")
            if not count.value:
                break
            result.extend(buffer.raw[: count.value])
            if len(result) > self.output_limit:
                lib.TerminateJobObject(self.job, 1)
                raise HookExecutionError("hook output exceeds the configured limit")
        return bytes(result)

    def _write(self, value: bytes) -> None:
        lib = kernel32()
        try:
            offset = 0
            while offset < len(value):
                count = wintypes.DWORD()
                chunk = value[offset : offset + 8192]
                if not lib.WriteFile(
                    self.stdin, chunk, len(chunk), ctypes.byref(count), None
                ):
                    if ctypes.get_last_error() in {109, 38}:
                        break
                    raise _err("write hook input")
                offset += count.value
        finally:
            _close(self.stdin)
            self.stdin = 0

    def _wait(self) -> int:
        lib = kernel32()
        if lib.WaitForSingleObject(self.process, 0xFFFFFFFF) != 0:
            raise _err("wait for hook process")
        code = wintypes.DWORD()
        if not lib.GetExitCodeProcess(self.process, ctypes.byref(code)):
            raise _err("read hook exit code")
        return int(code.value)

    async def communicate(self, input_bytes: bytes) -> tuple[bytes, bytes, int]:
        try:
            writer = asyncio.create_task(asyncio.to_thread(self._write, input_bytes))
            reader = asyncio.create_task(asyncio.to_thread(self._read))
            waiter = asyncio.create_task(asyncio.to_thread(self._wait))
            stdout, code = await asyncio.gather(reader, waiter)
            await writer
            return stdout, b"", code
        except Exception:
            await self.terminate_tree()
            raise
        finally:
            self._close()

    async def terminate_tree(self) -> None:
        if self.job:
            kernel32().TerminateJobObject(self.job, 1)
        if self.process:
            await asyncio.to_thread(self._wait)
        self._close()

    def _close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for handle in (self.stdin, self.stdout, self.process, self.job):
            _close(handle)
        self.stdin = self.stdout = self.process = self.job = 0
        _delete_appcontainer_profile(self.profile)
        shutil.rmtree(self.profile_storage, ignore_errors=True)


class WindowsAppContainerBackend:
    def supports(self, profile: str) -> bool:
        if os.name != "nt" or profile != HOOK_ISOLATION_PROFILE:
            return False
        try:
            userenv = ctypes.WinDLL("userenv", use_last_error=True)
            advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            required = (
                (userenv, "CreateAppContainerProfile"),
                (userenv, "DeleteAppContainerProfile"),
                (advapi, "ConvertSidToStringSidW"),
                (advapi, "FreeSid"),
            )
            return all(hasattr(library, symbol) for library, symbol in required)
        except (OSError, AttributeError):
            return False

    async def launch(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        limits: HookExecutionLimits,
        cancellation_token: asyncio.Event | None,
        read_only_root: Path,
        writable_root: Path,
    ) -> IsolatedProcess:
        if not self.supports(HOOK_ISOLATION_PROFILE):
            raise HookIsolationUnavailable("Windows AppContainer is unavailable")
        launch_task = asyncio.create_task(
            asyncio.to_thread(
                self._launch,
                argv,
                cwd,
                env,
                limits,
                read_only_root,
                writable_root,
                cancellation_token,
            )
        )
        try:
            return await asyncio.shield(launch_task)
        except asyncio.CancelledError as cancelled:
            if cancellation_token is not None:
                cancellation_token.set()
            try:
                process = await asyncio.shield(launch_task)
            except BaseException:
                raise cancelled
            await process.terminate_tree()
            raise cancelled

    def _launch(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        env: dict[str, str],
        limits: HookExecutionLimits,
        read_only_root: Path,
        writable_root: Path,
        cancellation_token: asyncio.Event | None,
    ) -> IsolatedProcess:
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.CreateAppContainerProfile.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.LPVOID),
        ]
        userenv.CreateAppContainerProfile.restype = ctypes.c_long
        name = f"EvoFlux.Hook.{uuid.uuid4().hex}"
        sid = wintypes.LPVOID()
        result = userenv.CreateAppContainerProfile(
            name,
            "EvoFlux Hook",
            "Per invocation plugin hook",
            None,
            0,
            ctypes.byref(sid),
        )
        if result:
            raise ctypes.WinError(result, "create hook AppContainer")
        sid_value = sid.value
        if sid_value is None:
            raise HookIsolationUnavailable("AppContainer profile has no SID")
        lib, handles, job = kernel32(), [], 0
        info = ProcessInformation()
        attrs = None
        profile_storage: Path | None = None
        try:
            if cancellation_token is not None and cancellation_token.is_set():
                raise _HookLaunchCancelled
            _restrict_tree(read_only_root, sid_value, writable=False)
            if cancellation_token is not None and cancellation_token.is_set():
                raise _HookLaunchCancelled
            _restrict_tree(writable_root, sid_value, writable=True)
            child_in, parent_in = _new_pipe(True)
            child_out, parent_out = _new_pipe(False)
            handles.extend((child_in, parent_in, child_out, parent_out))
            size = ctypes.c_size_t()
            lib.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            attrs = ctypes.create_string_buffer(size.value)
            if not lib.InitializeProcThreadAttributeList(
                attrs, 2, 0, ctypes.byref(size)
            ):
                raise _err("initialize AppContainer attributes")
            caps = SecurityCapabilities(sid_value, None, 0, 0)
            if not lib.UpdateProcThreadAttribute(
                attrs,
                0,
                PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(caps),
                ctypes.sizeof(caps),
                None,
                None,
            ):
                raise _err("set AppContainer security capabilities")
            # PROC_THREAD_ATTRIBUTE_HANDLE_LIST rejects duplicate handles even
            # when stdout and stderr intentionally share the same pipe.
            inherited = (wintypes.HANDLE * 2)(child_in, child_out)
            if not lib.UpdateProcThreadAttribute(
                attrs,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.byref(inherited),
                ctypes.sizeof(inherited),
                None,
                None,
            ):
                raise _err("restrict inherited handles")
            startup = StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = child_in
            startup.StartupInfo.hStdOutput = child_out
            startup.StartupInfo.hStdError = child_out
            startup.lpAttributeList = ctypes.cast(attrs, wintypes.LPVOID)
            root = os.environ.get("SystemRoot", r"C:\Windows")
            profile_storage = (
                Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                / "Packages"
                / name
            )
            appcontainer_root = profile_storage / "AC"
            profile_home = appcontainer_root / "Profile"
            roaming = appcontainer_root / "Roaming"
            profile_home.mkdir(parents=True, exist_ok=True)
            roaming.mkdir(parents=True, exist_ok=True)
            child_env = {
                **env,
                "SystemRoot": root,
                "WINDIR": root,
                "PATH": f"{root}\\System32;{Path(argv[0]).parent}",
                "LOCALAPPDATA": str(appcontainer_root),
                "APPDATA": str(roaming),
                "USERPROFILE": str(profile_home),
            }
            env_block = (
                "\0".join(
                    f"{k}={v}"
                    for k, v in sorted(
                        child_env.items(), key=lambda kv: kv[0].casefold()
                    )
                )
                + "\0\0"
            )
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            if cancellation_token is not None and cancellation_token.is_set():
                raise _HookLaunchCancelled
            if not lib.CreateProcessW(
                argv[0],
                command,
                None,
                None,
                True,
                CREATE_SUSPENDED
                | CREATE_UNICODE_ENVIRONMENT
                | EXTENDED_STARTUPINFO_PRESENT,
                ctypes.create_unicode_buffer(env_block),
                str(cwd),
                ctypes.byref(startup),
                ctypes.byref(info),
            ):
                raise _err("create AppContainer hook process")
            job = _new_job(limits)
            if not lib.AssignProcessToJobObject(job, info.hProcess):
                raise _err("assign hook Job Object")
            if cancellation_token is not None and cancellation_token.is_set():
                raise _HookLaunchCancelled
            for handle in (child_in, child_out):
                lib.CloseHandle(handle)
                handles.remove(handle)
            if lib.ResumeThread(info.hThread) == 0xFFFFFFFF:
                raise _err("resume isolated hook")
            if cancellation_token is not None and cancellation_token.is_set():
                raise _HookLaunchCancelled
            lib.CloseHandle(info.hThread)
            return WindowsProcess(
                int(info.hProcess),
                job,
                parent_out,
                parent_in,
                name,
                profile_storage,
                limits.max_output_bytes,
            )
        except Exception:
            if job:
                lib.TerminateJobObject(job, 1)
                lib.CloseHandle(job)
            if info.hThread:
                lib.CloseHandle(info.hThread)
                info.hThread = None
            if info.hProcess:
                lib.TerminateProcess(info.hProcess, 1)
                lib.WaitForSingleObject(info.hProcess, 5000)
                lib.CloseHandle(info.hProcess)
                info.hProcess = None
            for handle in set(handles):
                _close(handle)
            _delete_appcontainer_profile(name)
            if profile_storage is not None:
                shutil.rmtree(profile_storage, ignore_errors=True)
            raise
        finally:
            if attrs is not None:
                lib.DeleteProcThreadAttributeList(attrs)
            if sid:
                advapi = ctypes.WinDLL("advapi32", use_last_error=True)
                advapi.FreeSid.argtypes = [wintypes.LPVOID]
                advapi.FreeSid.restype = wintypes.LPVOID
                advapi.FreeSid(sid)


__all__ = ["WindowsAppContainerBackend"]
