"""Append-only, hash-chained CPU budget ledger with durable, independent checkpoints (G5 + reset protection).

Ledger file  : JSONL; event 0 is `genesis` (random ledger_id); every line carries seq / prev / hash.
Checkpoints  : >= 2 self-hashed JSON files in independent places (state dir + an anchor dir outside the state and
               code trees). Each records ledger_id, seq, head hash, totals and every campaign id ever used.
Every mutation (under an exclusive flock): verify the ledger chain AND every checkpoint (present, self-hash ok,
same ledger_id, its (seq, head) is a prefix of the ledger, ledger at most ONE event ahead = an interrupted
checkpoint write, rolled forward) -> append + fsync -> rewrite every checkpoint atomically (+ dir fsync).
Anything else fails closed:
  LedgerMissing (file gone while checkpoints exist), LedgerTamper (chain / torn tail / unknown event),
  CheckpointError(code): CHECKPOINT_MISSING, CHECKPOINT_CORRUPT, LEDGER_ID_MISMATCH, TRUNCATED_OR_ROLLED_BACK,
  FORK_OR_REPLAY, CHECKPOINT_STALE.
Genesis is explicit and first-ever only. Recovery actions (recover_ledger) need an owner approval token derived from
the current state; originals are preserved as *.bak; historical consumption is never reduced.
An older ledger module (edc2b6d and before) refuses this ledger (unknown `genesis` event): code rollback fails closed.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import glob
import hashlib
import json
import os
import shutil
import uuid

from . import CAP_CPU_S

GENESIS = "0" * 64
BUDGET_EVENTS = ("genesis", "reserve", "charge", "carry_forward", "checkpoint_rebuilt", "torn_tail_repaired",
                 "restored_from_backup")


class LedgerError(Exception):
    pass


class LedgerTamper(LedgerError):
    pass


class LedgerMissing(LedgerError):
    pass


class CheckpointError(LedgerError):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code


class ApprovalRequired(LedgerError):
    pass


class BudgetExceeded(Exception):
    pass


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _fsync_dir(d):
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: str, text: str):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)                  # only our own temp file; the previous version stays intact
        raise
    _fsync_dir(d)


def preserve(path: str, tag: str) -> str | None:
    """Copy (never move-and-delete) a file aside before any repair; returns the copy path."""
    if not os.path.exists(path):
        return None
    dst = f"{path}.{tag}-{_stamp()}.bak"
    shutil.copy2(path, dst)
    _fsync_dir(os.path.dirname(os.path.abspath(dst)))
    return dst


def _ev_hash(ev: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in ev.items() if k != "hash"}).encode()).hexdigest()


def parse_ledger_bytes(raw: bytes) -> tuple:
    """(events, torn_tail_bytes). Every complete line must chain; event 0 must be genesis."""
    try:
        text = raw.decode("utf-8", errors="strict") if raw else ""
    except UnicodeDecodeError as e:
        raise LedgerTamper(f"LEDGER_CORRUPT: not UTF-8 ({e})")
    torn = b""
    if text and not text.endswith("\n"):
        cut = text.rfind("\n") + 1
        torn, text = text[cut:].encode(), text[:cut]
    evs, prev = [], GENESIS
    for i, line in enumerate(text.splitlines()):
        try:
            ev = json.loads(line)
        except Exception as e:
            raise LedgerTamper(f"LEDGER_CORRUPT line {i}: unparseable ({e})")
        if ev.get("seq") != i or ev.get("prev") != prev or _ev_hash(ev) != ev.get("hash"):
            raise LedgerTamper(f"LEDGER_CORRUPT line {i}: chain broken")
        if ev.get("event") not in BUDGET_EVENTS:
            raise LedgerTamper(f"LEDGER_CORRUPT line {i}: unknown event {ev.get('event')}")
        if (i == 0) != (ev["event"] == "genesis"):
            raise LedgerTamper(f"LEDGER_CORRUPT line {i}: genesis must be exactly event 0")
        prev = ev["hash"]
        evs.append(ev)
    return evs, torn


def fold(evs: list, cap: float) -> dict:
    res, chg, used, carried = {}, {}, set(), 0.0
    for e in evs:
        k = e["event"]
        if k == "reserve":
            if e["campaign"] in used:
                raise LedgerTamper(f"campaign id reused: {e['campaign']}")
            used.add(e["campaign"])
            res[e["campaign"]] = e["amount_cpu_s"]
        elif k == "charge":
            if e["campaign"] not in res or e["campaign"] in chg:
                raise LedgerTamper(f"charge without open reservation {e['campaign']}")
            chg[e["campaign"]] = e["actual_cpu_s"]
        elif k == "carry_forward":
            carried += e["consumed_cpu_s"]
            used.update(e.get("campaigns", []))
    open_r = {c: a for c, a in res.items() if c not in chg}
    charged = carried + sum(chg.values())
    committed = charged + sum(open_r.values())
    return {"ledger_id": evs[0]["ledger_id"] if evs else None, "epoch": evs[0].get("epoch", 0) if evs else None,
            "charged_cpu_s": charged, "carried_forward_cpu_s": carried, "open_reservations": open_r,
            "committed_cpu_s": committed, "remaining_cpu_s": cap - committed, "events": len(evs),
            "seq": len(evs) - 1, "head": evs[-1]["hash"] if evs else GENESIS, "campaigns": sorted(used)}


def checkpoint_doc(st: dict, cap: float) -> dict:
    body = {"record": "tsb.mi.ledger_checkpoint", "version": 1, "ledger_id": st["ledger_id"], "epoch": st["epoch"],
            "seq": st["seq"], "head": st["head"], "events": st["events"], "charged_cpu_s": st["charged_cpu_s"],
            "committed_cpu_s": st["committed_cpu_s"], "open_reservations": st["open_reservations"],
            "campaigns": st["campaigns"], "cap_cpu_s": cap, "written_at": _now()}
    body["self_sha256"] = hashlib.sha256(_canon(body).encode()).hexdigest()
    return body


def read_checkpoint(path: str) -> dict:
    if not os.path.exists(path):
        raise CheckpointError("CHECKPOINT_MISSING", path)
    try:
        with open(path, encoding="utf-8") as fh:
            cp = json.load(fh)
        sh = cp.pop("self_sha256")
        ok = hashlib.sha256(_canon(cp).encode()).hexdigest() == sh and cp.get("record") == "tsb.mi.ledger_checkpoint"
        cp["self_sha256"] = sh
    except CheckpointError:
        raise
    except Exception as e:
        raise CheckpointError("CHECKPOINT_CORRUPT", f"{path}: {type(e).__name__}: {e}")
    if not ok:
        raise CheckpointError("CHECKPOINT_CORRUPT", f"{path}: self hash mismatch")
    return cp


class BudgetLedger:
    def __init__(self, path: str, cap_cpu_s: float = CAP_CPU_S, checkpoints=(), single_open: bool = False):
        self.path, self.cap = path, float(cap_cpu_s)
        self.checkpoints = list(checkpoints)
        self.single_open = single_open
        self.lock_path = path + ".lock"
        self.last_verify = None

    # ------------------------------------------------------------------ locking / reading
    @contextlib.contextmanager
    def _locked(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _raw(self) -> bytes | None:
        if not os.path.exists(self.path):
            return None
        with open(self.path, "rb") as fh:
            return fh.read()

    def _events(self) -> list:
        raw = self._raw()
        if raw is None:
            if any(os.path.exists(c) for c in self.checkpoints):
                raise LedgerMissing(f"LEDGER_MISSING: {self.path} absent but checkpoints exist (refusing; no reset)")
            raise LedgerMissing(f"NO_GENESIS: {self.path} absent and no checkpoint (first-ever genesis required)")
        evs, torn = parse_ledger_bytes(raw)
        if torn:
            raise LedgerTamper(f"TORN_TAIL: {len(torn)} trailing bytes without newline (interrupted write)")
        if not evs:
            raise LedgerTamper("LEDGER_CORRUPT: empty ledger file")
        return evs

    def _verify_checkpoints(self, evs, *, roll_forward: bool) -> dict:
        if not self.checkpoints:
            raise CheckpointError("CHECKPOINT_MISSING", "no checkpoint locations configured (refusing unverified use)")
        n, lid = len(evs), evs[0]["ledger_id"]
        cps = [read_checkpoint(p) for p in self.checkpoints]
        for p, cp in zip(self.checkpoints, cps):
            if cp["ledger_id"] != lid:
                raise CheckpointError("LEDGER_ID_MISMATCH", f"{p}: {cp['ledger_id']} != ledger {lid}")
            if cp["seq"] >= n:
                raise CheckpointError("TRUNCATED_OR_ROLLED_BACK", f"{p}: checkpoint seq {cp['seq']} >= ledger events {n}")
            if evs[cp["seq"]]["hash"] != cp["head"]:
                raise CheckpointError("FORK_OR_REPLAY", f"{p}: ledger hash at seq {cp['seq']} differs from checkpoint")
        lag = (n - 1) - (max(cp["seq"] for cp in cps) if cps else n - 1)
        rep = {"checkpoints": len(cps), "lag": lag, "rolled_forward": False}
        if lag > 1:
            raise CheckpointError("CHECKPOINT_STALE", f"ledger is {lag} events ahead of every checkpoint")
        if cps and (lag == 1 or any(cp["seq"] != n - 1 for cp in cps)) and roll_forward:
            self._write_checkpoints(fold(evs, self.cap))
            rep["rolled_forward"] = True
        self.last_verify = rep
        return rep

    def _write_checkpoints(self, st):
        doc = json.dumps(checkpoint_doc(st, self.cap), indent=1, sort_keys=True) + "\n"
        for p in self.checkpoints:
            atomic_write(p, doc)

    # ------------------------------------------------------------------ public read
    def state(self) -> dict:
        """Read-only, strict: raises on any integrity problem (never initializes anything)."""
        evs = self._events()
        rep = self._verify_checkpoints(evs, roll_forward=False)
        st = fold(evs, self.cap)
        st["verify"] = rep
        return st

    # ------------------------------------------------------------------ mutations
    def _append_locked(self, evs, body) -> dict:
        ev = dict(body, seq=len(evs), prev=evs[-1]["hash"] if evs else GENESIS, at=_now())
        ev["hash"] = _ev_hash(ev)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(_canon(ev) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(os.path.dirname(os.path.abspath(self.path)))
        evs = evs + [ev]
        self._write_checkpoints(fold(evs, self.cap))
        return ev

    def _mutate(self, build) -> dict:
        with self._locked():
            evs = self._events()
            self._verify_checkpoints(evs, roll_forward=True)
            body = build(fold(evs, self.cap))
            return self._append_locked(evs, body)

    def init_genesis(self, *, created_by: str, extra: dict | None = None) -> dict:
        """First-ever genesis ONLY: no ledger file, no checkpoint, no preserved *.bak copy anywhere."""
        with self._locked():
            leftovers = [p for p in [self.path, *self.checkpoints] if os.path.exists(p)]
            leftovers += glob.glob(self.path + ".*.bak") + [g for c in self.checkpoints for g in glob.glob(c + ".*.bak")]
            if leftovers:
                raise LedgerError(f"NOT_FIRST_GENESIS: existing ledger material {sorted(leftovers)[:4]} "
                                  "(use ledger-check / owner-approved recovery; never re-genesis)")
            if not self.checkpoints:
                raise LedgerError("genesis requires at least one independent checkpoint location")
            body = {"event": "genesis", "ledger_id": uuid.uuid4().hex, "epoch": 0, "cap_cpu_s": self.cap,
                    "created_by": created_by, **(extra or {})}
            return self._append_locked([], body)

    def reserve(self, campaign: str, amount_cpu_s: float) -> dict:
        if not amount_cpu_s > 0:
            raise ValueError("reservation must be positive")

        def build(st):
            if campaign in st["campaigns"]:
                raise BudgetExceeded(f"campaign id {campaign} was already used in this ledger lineage")
            if self.single_open and st["open_reservations"]:
                raise BudgetExceeded(f"another campaign is open: {sorted(st['open_reservations'])}")
            if st["committed_cpu_s"] + amount_cpu_s > self.cap:
                raise BudgetExceeded(f"committed {st['committed_cpu_s']} + {amount_cpu_s} > cap {self.cap}")
            return {"event": "reserve", "campaign": campaign, "amount_cpu_s": float(amount_cpu_s)}
        return self._mutate(build)

    def charge(self, campaign: str, actual_cpu_s: float, basis: str) -> dict:
        def build(st):
            if campaign not in st["open_reservations"]:
                raise LedgerTamper(f"no open reservation for {campaign}")
            return {"event": "charge", "campaign": campaign, "actual_cpu_s": float(actual_cpu_s), "basis": basis,
                    "reserved_cpu_s": st["open_reservations"][campaign]}
        return self._mutate(build)

    def recover(self, campaign: str) -> dict:
        """Crash recovery when the slice counter is gone: charge the FULL reservation (fail closed)."""
        def build(st):
            amt = st["open_reservations"].get(campaign)
            if amt is None:
                raise LedgerTamper(f"no open reservation for {campaign}")
            return {"event": "charge", "campaign": campaign, "actual_cpu_s": float(amt),
                    "basis": "recovered_full_reservation", "reserved_cpu_s": amt}
        return self._mutate(build)


# ====================================================================== diagnosis + owner-approved recovery
RECOVERY_ACTIONS = ("rebuild-checkpoints", "torn-tail", "restore-backup", "carry-forward")


def _best_checkpoint(ledger: BudgetLedger):
    good, bad = [], {}
    for p in ledger.checkpoints:
        try:
            good.append((p, read_checkpoint(p)))
        except CheckpointError as e:
            bad[p] = e.code
    best = max((cp for _, cp in good), key=lambda c: c["seq"], default=None)
    return best, good, bad


def diagnose(ledger: BudgetLedger) -> dict:
    """Read-only. Status + approval challenges for the applicable recovery actions. Never writes."""
    out = {"ledger": ledger.path, "checkpoints": ledger.checkpoints}
    best, good, bad = _best_checkpoint(ledger)
    out["checkpoint_status"] = {p: "ok" for p, _ in good} | bad
    try:
        st = ledger.state()
        out.update(status="OK", state={k: st[k] for k in ("ledger_id", "epoch", "seq", "charged_cpu_s",
                                                         "committed_cpu_s", "remaining_cpu_s", "open_reservations")},
                   verify=st["verify"])
        return out
    except LedgerMissing as e:
        out["status"] = str(e).split(":")[0]
    except CheckpointError as e:
        out["status"] = e.code
    except LedgerTamper as e:
        out["status"] = str(e).split(":")[0].split(" ")[0]
    out["best_checkpoint"] = {k: best[k] for k in ("ledger_id", "seq", "head", "committed_cpu_s")} if best else None
    out["approval_challenges"] = {a: challenge(ledger, a) for a in RECOVERY_ACTIONS}
    return out


def challenge(ledger: BudgetLedger, action: str) -> str:
    best, _, bad = _best_checkpoint(ledger)
    raw = ledger._raw()
    basis = "|".join(["MI-LEDGER-RECOVERY", action, os.path.abspath(ledger.path),
                      hashlib.sha256(raw).hexdigest() if raw is not None else "no-ledger",
                      best["head"] if best else "no-checkpoint", ",".join(sorted(bad))])
    return hashlib.sha256(basis.encode()).hexdigest()[:20]


def recover_ledger(ledger: BudgetLedger, action: str, *, approve: str, by: str, backup_path: str | None = None,
                   declared_consumed_cpu_s: float | None = None, declared_campaigns=()) -> dict:
    """Owner-approved recovery. Never reduces historical consumption; originals preserved as *.bak."""
    if action not in RECOVERY_ACTIONS:
        raise ValueError(action)
    with ledger._locked():
        want = challenge(ledger, action)
        if approve != want:
            raise ApprovalRequired(f"{action} needs owner approval token {want} (from `research-run mi ledger-check`)")
        best, good, _ = _best_checkpoint(ledger)
        raw = ledger._raw()
        note = {"approved_by": by, "approval": approve}
        if action == "rebuild-checkpoints":
            evs, torn = parse_ledger_bytes(raw or b"")
            if raw is None or torn or not evs:
                raise LedgerError("rebuild-checkpoints needs an intact ledger")
            for p, cp in good:
                if cp["ledger_id"] != evs[0]["ledger_id"] or cp["seq"] >= len(evs) or evs[cp["seq"]]["hash"] != cp["head"]:
                    raise LedgerError(f"surviving checkpoint {p} contradicts the ledger; use restore-backup / carry-forward")
            kept = [preserve(p, "corrupt") for p in ledger.checkpoints]
            return ledger._append_locked(evs, {"event": "checkpoint_rebuilt", **note, "preserved": [k for k in kept if k]})
        if action == "torn-tail":
            evs, torn = parse_ledger_bytes(raw or b"")
            if not torn or not evs:
                raise LedgerError("no torn tail to repair")
            for p, cp in good:
                if cp["ledger_id"] != evs[0]["ledger_id"] or cp["seq"] >= len(evs) or evs[cp["seq"]]["hash"] != cp["head"]:
                    raise LedgerError(f"checkpoint {p} is not a prefix of the intact part; refusing")
            kept = preserve(ledger.path, "torn")
            atomic_write(ledger.path, raw[: len(raw) - len(torn)].decode())
            return ledger._append_locked(evs, {"event": "torn_tail_repaired", **note, "preserved": kept,
                                               "removed_sha256": hashlib.sha256(torn).hexdigest(),
                                               "removed_bytes": len(torn)})
        if action == "restore-backup":
            if not backup_path or not best:
                raise LedgerError("restore-backup needs --backup and a surviving checkpoint to validate it")
            with open(backup_path, "rb") as fh:
                braw = fh.read()
            bevs, btorn = parse_ledger_bytes(braw)
            if btorn or not bevs or bevs[0]["ledger_id"] != best["ledger_id"] or len(bevs) - 1 < best["seq"] \
                    or bevs[best["seq"]]["hash"] != best["head"]:
                raise LedgerError("backup does not contain the checkpointed head of this ledger (older / foreign); "
                                  "use carry-forward")
            kept = preserve(ledger.path, "replaced")
            atomic_write(ledger.path, braw.decode())
            return ledger._append_locked(bevs, {"event": "restored_from_backup", **note, "backup": backup_path,
                                                "preserved": kept})
        # carry-forward: start a new epoch that carries the highest known consumption forward
        known = best["committed_cpu_s"] if best else None
        if known is None and declared_consumed_cpu_s is None:
            raise LedgerError("no checkpoint survives: the owner must declare prior consumption (--declared-consumed-cpu-s)")
        consumed = max(x for x in (known, declared_consumed_cpu_s) if x is not None)
        campaigns = sorted(set(best["campaigns"] if best else []) | set(declared_campaigns))
        kept = [preserve(p, "superseded") for p in ledger.checkpoints]
        if os.path.exists(ledger.path):                 # moved aside, never deleted
            dst = ledger.path + f".superseded-{_stamp()}.bak"
            os.replace(ledger.path, dst)
            kept.append(dst)
        gen = {"event": "genesis", "ledger_id": uuid.uuid4().hex, "epoch": (best["epoch"] + 1) if best else 1,
               "cap_cpu_s": ledger.cap, "created_by": by, "supersedes": best["ledger_id"] if best else None}
        g = ledger._append_locked([], gen)
        evs, _ = parse_ledger_bytes(ledger._raw())
        return ledger._append_locked(evs, {"event": "carry_forward", **note, "consumed_cpu_s": float(consumed),
                                           "campaigns": campaigns, "from_checkpoint_head": best["head"] if best else None,
                                           "preserved": [k for k in kept if k], "genesis": g["hash"]})
