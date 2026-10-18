"""Persistent local incident state (P2-CR Package G). Minimal by design: no delivery, no platform.

Files under <data_dir>/incidents/ (survive restarts; never deleted by the collector):
  state.json          current incidents (atomic replace)
  events.jsonl        append-only history: open / update / resolve / ack (fsynced)
  ack/<id>.json       OPERATOR-written acknowledgement {"by": ..., "ref": ...} (the collector only reads it)
  external/*.json     incidents raised by host-side jobs (daily seal, backup): read-only to the collector

Every distinct occurrence of a condition after the previous incident for it was resolved or acknowledged opens a NEW
incident (new id), so an earlier quarantine or error can never mask a later independent one. A latched incident
(integrity events) stays active until an operator acknowledges it; a state-like incident (disk warning, refresh
failure, clock) resolves when its condition clears. Each incident keeps its first / last occurrence details.
"""
from __future__ import annotations

import json
import os
import time

SEVERITIES = ("INFO", "WARNING", "DEGRADED", "CRITICAL")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class IncidentLog:
    def __init__(self, base: str, boot_id: str):
        self.dir = os.path.join(base, "incidents")
        self.boot8 = boot_id[:8]
        self.items = {}                       # id -> incident
        self.n = 0
        self.dirty_ms = None
        self.write_errors = 0
        os.makedirs(os.path.join(self.dir, "ack"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "external"), exist_ok=True)
        try:
            with open(os.path.join(self.dir, "state.json"), encoding="utf-8") as fh:
                for inc in json.load(fh).get("incidents", []):
                    self.items[inc["id"]] = inc
        except FileNotFoundError:
            pass
        self.dirty_ms = now_ms()                                    # state.json always exists after a start

    # ---- queries ----
    def _open_for(self, key: str):
        for inc in self.items.values():
            if inc["key"] == key and inc["active"] and inc["ack"] is None:
                return inc
        return None

    def active(self) -> list:
        return sorted((i for i in self.items.values() if i["active"] and i["ack"] is None), key=lambda i: i["first_ms"])

    def summary(self) -> dict:
        act = self.active()
        return {"active": [{k: i[k] for k in ("id", "key", "severity", "first_ms", "last_ms", "count", "latched")}
                           for i in act][:50],
                "active_count": len(act), "by_severity": {s: sum(1 for i in act if i["severity"] == s) for s in SEVERITIES},
                "total": len(self.items), "write_errors": self.write_errors}

    # ---- mutations ----
    def raise_(self, key: str, severity: str, detail=None, latched: bool = True) -> dict:
        m = now_ms()
        inc = self._open_for(key)
        if inc is None:
            self.n += 1
            inc = {"id": f"inc-{m}-{self.boot8}-{self.n}", "key": key, "severity": severity, "latched": latched,
                   "first_ms": m, "last_ms": m, "count": 1, "active": True, "resolved_ms": None, "ack": None,
                   "boot8": self.boot8, "first_detail": detail, "last_detail": detail}
            self.items[inc["id"]] = inc
            self._event("open", inc, detail)
        else:
            inc["last_ms"], inc["count"], inc["last_detail"] = m, inc["count"] + 1, detail
            if SEVERITIES.index(severity) > SEVERITIES.index(inc["severity"]):
                inc["severity"] = severity
            self._event("update", inc, detail)
        self.dirty_ms = m
        return inc

    def resolve(self, key: str) -> None:
        inc = self._open_for(key)
        if inc is not None and not inc["latched"]:
            inc["active"], inc["resolved_ms"] = False, now_ms()
            self._event("resolve", inc, None)
            self.dirty_ms = inc["resolved_ms"]

    def poll_acks(self) -> int:
        """Operator acknowledgements (bounded: one small file per acknowledged incident)."""
        n, d = 0, os.path.join(self.dir, "ack")
        for f in os.listdir(d):
            iid = f[:-5] if f.endswith(".json") else None
            inc = self.items.get(iid)
            if inc is None or inc["ack"] is not None:
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    a = json.load(fh)
                ack = {"by": str(a.get("by"))[:80], "ref": str(a.get("ref"))[:200], "ack_ms": now_ms()}
            except (OSError, ValueError, AttributeError):
                continue
            inc["ack"] = ack
            self._event("ack", inc, ack)
            n += 1
        if n:
            self.dirty_ms = now_ms()
        return n

    def poll_external(self) -> None:
        """Host-side job incidents (daily seal / backup failures): one file each, raised once as CRITICAL."""
        d = os.path.join(self.dir, "external")
        known = {i["key"] for i in self.items.values()}
        for f in sorted(os.listdir(d)):
            key = f"external:{f}"
            if not f.endswith(".json") or key in known:
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    detail = json.load(fh)
            except (OSError, ValueError):
                detail = {"unreadable": True}
            sev = detail.get("severity") if isinstance(detail, dict) and detail.get("severity") in SEVERITIES else "CRITICAL"
            self.raise_(key, sev, detail, latched=True)

    def _event(self, kind: str, inc: dict, detail) -> None:
        try:
            with open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts_ms": now_ms(), "event": kind, "id": inc["id"], "key": inc["key"],
                                     "severity": inc["severity"], "count": inc["count"], "detail": detail},
                                    sort_keys=True, default=str) + "\n")
                fh.flush(); os.fsync(fh.fileno())
        except OSError:
            self.write_errors += 1

    def flush(self) -> None:
        if self.dirty_ms is None:
            return
        p = os.path.join(self.dir, "state.json")
        try:
            with open(p + ".tmp", "w", encoding="utf-8") as fh:
                json.dump({"updated_ms": now_ms(), "incidents": sorted(self.items.values(), key=lambda i: i["first_ms"])},
                          fh, sort_keys=True, default=str)
                fh.flush(); os.fsync(fh.fileno())
            os.replace(p + ".tmp", p)
            self.dirty_ms = None
        except OSError:
            self.write_errors += 1
