"""Append-only, hash-chained CPU budget ledger (G5). Every mutation happens under an exclusive flock and only after
the whole chain verifies; any defect raises LedgerTamper so callers fail closed.

Events: reserve(campaign, amount) / charge(campaign, actual, basis). An open reservation (no charge yet) counts as
fully consumed, so a crash between reserve and charge can never free budget.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os

from . import CAP_CPU_S

GENESIS = "0" * 64


class LedgerTamper(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class BudgetLedger:
    def __init__(self, path: str, cap_cpu_s: float = CAP_CPU_S):
        self.path, self.cap = path, float(cap_cpu_s)
        self.lock_path = path + ".lock"

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

    def _events(self) -> list:
        if not os.path.exists(self.path):
            return []
        out, prev = [], GENESIS
        with open(self.path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                try:
                    ev = json.loads(line)
                except Exception as e:
                    raise LedgerTamper(f"line {i}: unparseable ({e})")
                h = ev.pop("hash", None)
                if ev.get("seq") != i or ev.get("prev") != prev or hashlib.sha256(_canon(ev).encode()).hexdigest() != h:
                    raise LedgerTamper(f"line {i}: chain broken")
                ev["hash"] = prev = h
                out.append(ev)
        return out

    def state(self) -> dict:
        evs = self._events()
        res, chg = {}, {}
        for e in evs:
            if e["event"] == "reserve":
                if e["campaign"] in res:
                    raise LedgerTamper(f"duplicate reservation {e['campaign']}")
                res[e["campaign"]] = e["amount_cpu_s"]
            elif e["event"] == "charge":
                if e["campaign"] not in res or e["campaign"] in chg:
                    raise LedgerTamper(f"charge without open reservation {e['campaign']}")
                chg[e["campaign"]] = e["actual_cpu_s"]
            else:
                raise LedgerTamper(f"unknown event {e['event']}")
        open_r = {c: a for c, a in res.items() if c not in chg}
        charged = sum(chg.values())
        committed = charged + sum(open_r.values())
        return {"charged_cpu_s": charged, "open_reservations": open_r, "committed_cpu_s": committed,
                "remaining_cpu_s": self.cap - committed, "events": len(evs),
                "head": evs[-1]["hash"] if evs else GENESIS}

    def _append(self, body: dict) -> dict:
        evs = self._events()
        ev = dict(body, seq=len(evs), prev=evs[-1]["hash"] if evs else GENESIS, at=_now())
        ev["hash"] = hashlib.sha256(_canon(ev).encode()).hexdigest()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(_canon(ev) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return ev

    def reserve(self, campaign: str, amount_cpu_s: float) -> dict:
        if not amount_cpu_s > 0:
            raise ValueError("reservation must be positive")
        with self._locked():
            st = self.state()
            if campaign in st["open_reservations"]:
                raise BudgetExceeded(f"campaign {campaign} already open")
            if st["committed_cpu_s"] + amount_cpu_s > self.cap:
                raise BudgetExceeded(f"committed {st['committed_cpu_s']} + {amount_cpu_s} > cap {self.cap}")
            return self._append({"event": "reserve", "campaign": campaign, "amount_cpu_s": float(amount_cpu_s)})

    def charge(self, campaign: str, actual_cpu_s: float, basis: str) -> dict:
        with self._locked():
            st = self.state()
            if campaign not in st["open_reservations"]:
                raise LedgerTamper(f"no open reservation for {campaign}")
            return self._append({"event": "charge", "campaign": campaign, "actual_cpu_s": float(actual_cpu_s),
                                 "basis": basis, "reserved_cpu_s": st["open_reservations"][campaign]})

    def recover(self, campaign: str) -> dict:
        """Crash recovery when the slice counter is gone: charge the FULL reservation (fail closed)."""
        with self._locked():
            st = self.state()
            amt = st["open_reservations"].get(campaign)
            if amt is None:
                raise LedgerTamper(f"no open reservation for {campaign}")
        return self.charge(campaign, amt, "recovered_full_reservation")
