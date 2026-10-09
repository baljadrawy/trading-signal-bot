"""Fail-closed runtime data-access restriction for Phase 1S (PEP 578 audit hook, allow-list).

Policy (realpath-resolved):
  read   only: the MI package dir (code + frozen contracts_v1_0), p2_research/__init__.py, the Python stdlib,
               /proc/self, /dev/null, /dev/urandom, the output dir and explicitly passed extra read files
  write  only: under the output dir
  deny   always (checked first, clearer error): research-data, backups, the CPU-guard ledger / anchor dirs,
               ~/.config/research-runner, ~/ops (runner + P2 forward), the production checkout, docker / postgres
               sockets and data dirs
  never: subprocess / exec / spawn / os.system, sockets (create / connect / bind / getaddrinfo), sqlite3, ctypes,
         DB clients and imports of reader / stream / ledger / execution / P2-forward / runner / guard modules;
         os.fork only when the caller allows a worker pool (children inherit the hook)

Threat model and limits (see docs/mi/MI_PHASE1S_IMPL.md, section "Isolation"): this guards against ACCIDENTAL access
by this package's own code and its stdlib dependencies. It is NOT a security boundary: native extensions, code that
ran before install(), already-open inherited descriptors and in-process mutation of interpreter state are outside
its reach. A violation raises in the offending call AND is recorded; check() re-raises after any library swallowed
the exception, so the run fails closed. OS-level isolation (systemd InaccessiblePaths / PrivateNetwork / ReadOnly
paths on the job unit) is an additional pre-pilot requirement, not provided here.
"""
from __future__ import annotations

import os
import sys
import sysconfig

HOME = os.path.expanduser("~")
DENY = tuple(os.path.realpath(p) for p in (
    os.path.join(HOME, "research-data"), os.path.join(HOME, "backups"),
    os.path.join(HOME, ".local", "state", "research-runner"), os.path.join(HOME, ".config", "research-runner"),
    os.path.join(HOME, "ops"), os.path.join(HOME, "trading-signal-bot"), os.path.join(HOME, ".config", "tsb-backup"),
    "/var/run/docker.sock", "/run/docker.sock", "/run/postgresql", "/var/run/postgresql", "/var/lib/postgresql",
    "/var/lib/docker"))
DENY_IMPORT_PREFIX = ("sqlite3", "_sqlite3", "psycopg", "psycopg2", "asyncpg", "pg8000", "sqlalchemy", "docker",
                      "requests", "urllib3", "aiohttp", "httpx", "http.client", "urllib.request", "ftplib", "smtplib",
                      "ctypes", "_ctypes", "cffi", "subprocess", "p2_research.reader", "p2_research.stream",
                      "p2_research.ledger", "p2_research.execution", "p2_forward", "mi_cpuguard", "research_exec")
DENY_EVENTS = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.forkpty", "pty.spawn",
               "socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto",
               "sqlite3.connect", "ctypes.dlopen", "ctypes.dlsym", "ctypes.cdata", "urllib.Request", "webbrowser.open",
               "os.startfile", "winreg")
PATH_EVENTS_READ = ("os.listdir", "os.scandir", "glob.glob")
PATH_EVENTS_WRITE1 = ("os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate",
                      "os.unlink", "shutil.rmtree", "os.chflags", "os.lchmod", "os.lchown", "os.setxattr",
                      "os.removexattr")
PATH_EVENTS_WRITE2 = ("os.rename", "os.replace", "os.link", "os.symlink", "shutil.copyfile", "shutil.copytree",
                      "shutil.move")
W_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

_STATE = {"installed": False, "violations": []}


class SandboxViolation(PermissionError):
    pass


def _under(p: str, roots) -> bool:
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def stdlib_roots() -> tuple:
    paths = {sysconfig.get_paths()[k] for k in ("stdlib", "platstdlib")}
    paths.add(os.path.dirname(os.__file__))
    dyn = os.path.join(sysconfig.get_paths()["platstdlib"], "lib-dynload")
    paths.add(dyn)
    return tuple(sorted(os.path.realpath(p) for p in paths))


def install(out_dir: str, extra_read=(), allow_fork: bool = False) -> None:
    """Install once per process. Must be called before any engine import that is not already loaded."""
    if _STATE["installed"]:
        raise SandboxViolation("sandbox already installed")
    sys.dont_write_bytecode = True
    pkg_mi = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    p2_init = os.path.realpath(os.path.join(pkg_mi, "..", "__init__.py"))
    out = os.path.realpath(out_dir)
    if _under(out, DENY) or _under(out, (pkg_mi,)):
        raise SandboxViolation(f"output dir not allowed: {out}")
    read_roots = (pkg_mi, p2_init, out, f"/proc/{os.getpid()}", "/dev/null", "/dev/urandom") + \
        stdlib_roots() + tuple(os.path.realpath(p) for p in extra_read)
    write_roots = (out, "/dev/null")
    deny, deny_imp, deny_ev = DENY, DENY_IMPORT_PREFIX, DENY_EVENTS
    fork_ok = bool(allow_fork)
    violations = _STATE["violations"]

    def fail(what):
        violations.append(what)
        raise SandboxViolation(f"PHASE1S_SANDBOX: {what}")

    def check_path(path, write):
        if isinstance(path, int):
            return
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, str):
            fail(f"non-path argument {type(path).__name__}")
        if not write and path.startswith("/proc/self/"):
            return
        rp = os.path.realpath(path)
        if _under(rp, deny):
            fail(f"denied path {rp}")
        if write and not _under(rp, write_roots):
            fail(f"write outside output dir: {rp}")
        if not write and not _under(rp, read_roots):
            fail(f"read outside allow-list: {rp}")

    def hook(event, args):
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            write = bool(isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                bool(isinstance(flags, int) and flags & W_FLAGS)
            check_path(path, write)
        elif event == "import":
            name = args[0] or ""
            for pfx in deny_imp:
                if name == pfx or name.startswith(pfx + "."):
                    fail(f"denied import {name}")
        elif event in PATH_EVENTS_READ:
            check_path(args[0] if args and args[0] is not None else ".", False)
        elif event in PATH_EVENTS_WRITE1:
            check_path(args[0], True)
        elif event in PATH_EVENTS_WRITE2:
            check_path(args[0], True)
            check_path(args[1], True)
        elif event == "os.fork":
            if not fork_ok:
                fail("fork not allowed")
        else:
            for ev in deny_ev:
                if event == ev or event.startswith(ev + "."):
                    fail(f"denied event {event}")

    sys.addaudithook(hook)
    _STATE["installed"] = True


def violations() -> list:
    return list(_STATE["violations"])


def check() -> None:
    """Fail closed if any violation was recorded, even one a library caught and swallowed."""
    if _STATE["violations"]:
        raise SandboxViolation(f"PHASE1S_SANDBOX: {len(_STATE['violations'])} violation(s): "
                               f"{_STATE['violations'][:3]}")


MI_SLICE_MARK = "/research.slice/research-mi.slice/"


def require_mi_slice() -> str:
    """Pilot / full refuse to run outside research-mi.slice (the MI CPU guard's kernel-capped envelope)."""
    with open("/proc/self/cgroup", encoding="ascii") as fh:
        cg = fh.read()
    if MI_SLICE_MARK not in cg:
        raise SandboxViolation(f"NOT_IN_MI_SLICE: {cg.strip()}")
    return cg.strip()
