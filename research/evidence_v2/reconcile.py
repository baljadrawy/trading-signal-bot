"""Offline data-quality reconciliation for evidence v2 (P1-E).

    python -m research.evidence_v2.reconcile --dir data/evidence_v2 [--now 2026-10-01T00:00:00Z]
                                             [--since 2026-09-28T00:00:00Z] [--json report.json]

Detects: malformed/invalid records, duplicate and conflicting event ids, per-boot sequence gaps
(lost events), missing lifecycle stages, incomplete/stale trade lifecycles, stale features,
point-in-time violations, and recorder health problems (errors, drops, stale flush).

OUTCOME-BLIND BY DESIGN: it reads identities, stage presence, decisions and timestamps only.
It never reads profit, result or exit-price fields, so it can run on forward data without
computing any performance statistic. Standard library only. Exit code: 0 ok, 1 warnings,
2 critical findings.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from collections import defaultdict

SCHEMA = "tsb.evidence"
SCHEMA_VERSION = 2
REQUIRED = ("schema", "schema_version", "event_id", "event_type", "service", "boot_id", "seq",
            "event_time_ms", "recorded_at_ms", "strategy_version", "code_sha", "config_hash",
            "subject", "state", "payload")
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
MAX_TRADE_HOURS = {"15m": 48, "1h": 96, "4h": 96, "1d": 240}      # tracker expiry policy
ANALYSIS_WINDOW_MS = 30 * 60_000                                    # signal_engine SQL window
SLACK_MS = 5 * 60_000
DELIVERY_WINDOW_MS = 30 * 60_000
ADMISSION_WINDOW_MS = 2 * 3_600_000 + 15 * 60_000
MACRO_MAX_STALE_S = 2 * 3600
STALE_FLUSH_MS = 15 * 60_000
SEVERITY = {"critical": 2, "warning": 1, "info": 0}


def iso_ms(text: str) -> int:
    return int(dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


class Report:
    def __init__(self):
        self.findings = defaultdict(list)       # code -> [details]
        self.severity = {}

    def add(self, severity: str, code: str, **details):
        self.severity[code] = severity
        if len(self.findings[code]) < 200:      # keep reports bounded; counts stay exact
            self.findings[code].append(details)
        self.findings.setdefault(code + "#count", [0])[0] += 1

    def worst(self) -> int:
        return max((SEVERITY[s] for c, s in self.severity.items()), default=0)

    def as_dict(self) -> dict:
        out = {}
        for code, sev in sorted(self.severity.items()):
            out[code] = {"severity": sev, "count": self.findings[code + "#count"][0],
                         "examples": self.findings[code][:20]}
        return out


def load(directory: str, report: Report) -> list[dict]:
    events = []
    for path in sorted(glob.glob(os.path.join(directory, "*", "events-*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    report.add("critical", "malformed_line", file=os.path.basename(path), line=lineno)
                    continue
                missing = [k for k in REQUIRED if k not in rec]
                if missing or rec.get("schema") != SCHEMA or rec.get("schema_version") != SCHEMA_VERSION:
                    report.add("critical", "invalid_record", file=os.path.basename(path), line=lineno,
                               missing=missing, schema=rec.get("schema"),
                               schema_version=rec.get("schema_version"))
                    continue
                events.append(rec)
    return events


def check_duplicates(events, report):
    by_id = defaultdict(list)
    for e in events:
        by_id[e["event_id"]].append(e)
    unique = []
    for eid, group in by_id.items():
        unique.append(group[0])
        if len(group) > 1:
            facts = {json.dumps([g["event_type"], g["subject"], g["state"]], sort_keys=True) for g in group}
            if len(facts) > 1:
                report.add("critical", "conflicting_event_id", event_id=eid, variants=len(facts))
            else:
                report.add("info", "duplicate_event_restated", event_id=eid,
                           event_type=group[0]["event_type"], copies=len(group),
                           boots=len({g["boot_id"] for g in group}))
    return unique


def _stats_files(directory):
    out = {}
    for path in glob.glob(os.path.join(directory, "*", "_recorder_stats.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                out[os.path.basename(os.path.dirname(path))] = json.load(fh)
        except (OSError, ValueError):
            pass
    return out


def check_sequences(events, report, directory):
    by_boot = defaultdict(list)
    last_stats = {}
    for e in events:
        by_boot[(e["service"], e["boot_id"])].append(e["seq"])
        if e["event_type"] in ("recorder.stats", "recorder.stopping"):
            key = (e["service"], e["boot_id"])
            if key not in last_stats or e["seq"] > last_stats[key]["seq"]:
                last_stats[key] = e
    # Upper bound per boot: the recorder's own seq minus what was still queued when it reported.
    # This reveals losses at the END of a boot, which leave no internal gap.
    bound = {}
    for (service, boot), e in last_stats.items():
        p = e.get("payload") or {}
        bound[(service, boot)] = (p.get("seq") or 0) - (p.get("queue_depth") or 0)
    for service, st in _stats_files(directory).items():
        key = (service, st.get("boot_id"))
        bound[key] = max(bound.get(key, 0), (st.get("seq") or 0) - (st.get("queue_depth") or 0))
    for (service, boot), seqs in sorted(by_boot.items()):
        seqs = sorted(set(seqs))
        missing = (seqs[-1] - seqs[0] + 1 - len(seqs)) + (seqs[0] - 1)
        missing += max(0, bound.get((service, boot), 0) - seqs[-1])
        if missing > 0:
            stats = (last_stats.get((service, boot)) or {}).get("payload", {})
            report.add("warning", "sequence_gap_lost_events", service=service, boot_id=boot,
                       lost=missing, recorder_reported_dropped=stats.get("dropped"))
    return last_stats


def check_recorder_health(events, last_stats, directory, now_ms, report):
    latest = {}
    for (service, boot), e in last_stats.items():
        if service not in latest or e["recorded_at_ms"] > latest[service]["recorded_at_ms"]:
            latest[service] = e
    for path in glob.glob(os.path.join(directory, "*", "_recorder_stats.json")):
        service = os.path.basename(os.path.dirname(path))
        try:
            with open(path, encoding="utf-8") as fh:
                stats = json.load(fh)
            latest.setdefault(service, {"payload": stats, "recorded_at_ms": None})
            latest[service] = {"payload": stats, "recorded_at_ms": latest[service].get("recorded_at_ms")}
        except (OSError, ValueError):
            report.add("warning", "stats_file_unreadable", service=service)
    health = {}
    for service, e in sorted(latest.items()):
        s = e.get("payload") or {}
        health[service] = {k: s.get(k) for k in ("queue_depth", "max_depth_seen", "dropped", "errors",
                                                 "hook_errors", "flush_failures", "last_flush_ok_at",
                                                 "last_error", "emitted", "suppressed_repeats")}
        for field, sev in (("dropped", "warning"), ("errors", "warning"), ("hook_errors", "warning"),
                           ("flush_failures", "warning")):
            if (s.get(field) or 0) > 0:
                report.add(sev, f"recorder_{field}", service=service, value=s.get(field),
                           last_error=s.get("last_error"))
        flush = s.get("last_flush_ok_at")
        if flush and now_ms - iso_ms(flush) > STALE_FLUSH_MS:
            report.add("warning", "recorder_stale_flush", service=service, last_flush_ok_at=flush)
    return health


def _pit_checks(e, report):
    """Availability timestamps must precede the decision (event_time); candles must be closed."""
    p = e.get("payload") or {}
    pit = p.get("pit") or {}
    decision = e["event_time_ms"]
    tf = (e.get("subject") or {}).get("timeframe")
    order = [("candle_close_time_ms", "klines_fetched_at_ms"),
             ("klines_fetched_at_ms", "analyzed_at_ms")]
    for earlier, later in order:
        a, b = pit.get(earlier), pit.get(later)
        if a is not None and b is not None and a > b:
            report.add("critical", "pit_violation", event_id=e["event_id"], earlier=earlier,
                       later=later, by_ms=a - b)
    for field in ("candle_close_time_ms", "klines_fetched_at_ms", "analyzed_at_ms",
                  "orderbook_fetched_at_ms"):
        v = pit.get(field)
        if v is not None and v > decision:
            report.add("critical", "pit_violation", event_id=e["event_id"], earlier=field,
                       later="event_time_ms", by_ms=v - decision)
    macro_valid = (p.get("macro") or {}).get("macro_valid_at_ms")
    if macro_valid is not None and macro_valid > decision + 1000:
        report.add("critical", "pit_violation", event_id=e["event_id"], earlier="macro_valid_at_ms",
                   later="event_time_ms", by_ms=macro_valid - decision)
    opened = pit.get("candle_open_time_ms")
    if opened is not None and tf in TF_MS and opened % TF_MS[tf] != 0:
        report.add("warning", "candle_misaligned", event_id=e["event_id"], timeframe=tf)


def _staleness(e, report):
    p = e.get("payload") or {}
    pit = p.get("pit") or {}
    decision = e["event_time_ms"]
    tf = (e.get("subject") or {}).get("timeframe")
    state = e.get("state") or {}
    close = pit.get("candle_close_time_ms")
    if close is not None and tf in TF_MS and decision - close > TF_MS[tf] + ANALYSIS_WINDOW_MS + SLACK_MS:
        report.add("warning", "stale_candle", event_id=e["event_id"], timeframe=tf,
                   age_min=round((decision - close) / 60000, 1))
    analyzed = pit.get("analyzed_at_ms")
    if analyzed is not None and decision - analyzed > ANALYSIS_WINDOW_MS + SLACK_MS:
        report.add("warning", "stale_analysis", event_id=e["event_id"],
                   age_min=round((decision - analyzed) / 60000, 1))
    ob = pit.get("orderbook_fetched_at_ms")
    if ob is not None and decision - ob > ANALYSIS_WINDOW_MS + SLACK_MS:
        report.add("warning", "stale_orderbook", event_id=e["event_id"],
                   age_min=round((decision - ob) / 60000, 1))
    age = (p.get("macro") or {}).get("macro_age_seconds")
    if age is not None and age > MACRO_MAX_STALE_S and state.get("reason") != "macro_block":
        report.add("critical", "stale_macro_used", event_id=e["event_id"], age_s=age)
    if e["event_type"] == "candidate.evaluated" and p.get("identity_status") == "missing_pit":
        report.add("info", "candidate_without_pit_identity", event_id=e["event_id"])


def check_lineage(events, now_ms, report, first_recording_ms):
    by_type = defaultdict(list)
    for e in events:
        by_type[e["event_type"]].append(e)
    analyzed = {e["subject"].get("candidate_id") for e in by_type["candidate.analyzed"]}
    selected = {e["subject"].get("candidate_id") for e in by_type["candidate.evaluated"]
                if (e.get("state") or {}).get("decision") == "selected"}
    created = {}
    # P1-R: the evidence event for a committed policy_ready signal is `signal.ready` (it mirrors
    # the runtime outbox event of the same name; there is no `signal.created` in the CR-2 contract).
    for e in by_type["signal.ready"]:
        created[e["subject"].get("signal_id")] = e
        cid = e["subject"].get("candidate_id")
        if cid and cid not in selected:
            report.add("warning", "signal_without_selected_evaluation", signal_id=e["subject"]["signal_id"])
        if cid and analyzed and cid not in analyzed:
            report.add("warning", "signal_without_analysis_event", signal_id=e["subject"]["signal_id"])
    delivery = defaultdict(list)
    for t in ("delivery.sent", "delivery.refused", "delivery.skipped", "delivery.approval_requested"):
        for e in by_type[t]:
            delivery[e["subject"].get("signal_id")].append(e)
    admission = defaultdict(list)
    for t in ("admission.decision", "entry.attempt", "trade.opened", "delivery.consumed",
              "entry.expired"):
        for e in by_type[t]:
            admission[e["subject"].get("signal_id")].append(e)

    def orphan(code, e, sid):
        sev = "info" if e["event_time_ms"] < first_recording_ms + ADMISSION_WINDOW_MS else "warning"
        report.add(sev, code, signal_id=sid, event_type=e["event_type"])

    for sid, e in created.items():
        due = e["event_time_ms"] + DELIVERY_WINDOW_MS
        if sid not in delivery and now_ms > due:
            report.add("warning", "missing_delivery_stage", signal_id=sid)
        sent = [d for d in delivery.get(sid, []) if d["event_type"] == "delivery.sent"]
        if sent and sid not in admission and now_ms > sent[0]["event_time_ms"] + ADMISSION_WINDOW_MS:
            report.add("warning", "missing_admission_stage", signal_id=sid)
    for sid, evs in delivery.items():
        if sid is not None and sid not in created:
            orphan("delivery_without_signal_event", evs[0], sid)
    for sid, evs in admission.items():
        if sid not in created:
            orphan("admission_without_signal_event", evs[0], sid)
    # P1-R: a deferral that exhausts the outbox attempts dead-letters the runtime event. Evidence
    # must say why; only a dead letter with no observed admission/entry outcome is unexplained.
    dead_letters = {"explained": 0, "unexplained": 0}
    for e in by_type["delivery.consumed"]:
        p = e.get("payload") or {}
        if p.get("final_attempt"):
            if p.get("outcome_code") in ("DEFERRED_UNOBSERVED", "UNKNOWN", None):
                dead_letters["unexplained"] += 1
                report.add("warning", "unexplained_dead_letter", signal_id=e["subject"].get("signal_id"),
                           outbox_event_id=p.get("outbox_event_id"))
            else:
                dead_letters["explained"] += 1
    for e in by_type["entry.expired"]:
        if (e.get("payload") or {}).get("outcome_code") == "EXPIRED_UNOBSERVED":
            report.add("info", "expiry_without_observed_attempt", signal_id=e["subject"].get("signal_id"))
    opened = {e["subject"].get("active_trade_id"): e for e in by_type["trade.opened"]}
    closed = {e["subject"].get("active_trade_id"): e for e in by_type["trade.closed"]}
    lifecycle = {"opened": len(opened), "closed": len(closed), "open_within_horizon": 0,
                 "stale_open": 0, "dead_letters": dead_letters}
    for tid, e in opened.items():
        if tid in closed:
            continue
        tf = e["subject"].get("timeframe")
        horizon = (MAX_TRADE_HOURS.get(tf, 240) + 2) * 3_600_000
        if now_ms - e["event_time_ms"] > horizon:
            lifecycle["stale_open"] += 1
            report.add("warning", "incomplete_trade_lifecycle", active_trade_id=tid, timeframe=tf)
        else:
            lifecycle["open_within_horizon"] += 1
    for tid, e in closed.items():
        if tid not in opened:
            sev = "info" if e["event_time_ms"] < first_recording_ms + 10 * 86_400_000 else "warning"
            report.add(sev, "closed_without_open_event", active_trade_id=tid)
    for e in by_type["trade.target_hit"]:
        if e["subject"].get("active_trade_id") not in opened:
            report.add("info", "target_hit_without_open_event",
                       active_trade_id=e["subject"].get("active_trade_id"))
    return lifecycle


def reconcile(directory: str, now_ms: int, since_ms: int | None = None) -> dict:
    report = Report()
    raw = load(directory, report)                 # sequence/duplicate checks see every record
    events = check_duplicates(raw, report)
    last_stats = check_sequences(raw, report, directory)
    if since_ms is not None:                      # the analysis window only narrows lineage checks
        events = [e for e in events if e["event_time_ms"] >= since_ms]
    health = check_recorder_health(events, last_stats, directory, now_ms, report)
    starts = [e["event_time_ms"] for e in events if e["event_type"] == "recorder.started"]
    first_recording_ms = min(starts) if starts else min((e["event_time_ms"] for e in events), default=now_ms)
    for e in events:
        if e["event_type"] in ("candidate.evaluated", "signal.ready", "candidate.analyzed"):
            _pit_checks(e, report)
            if e["event_type"] != "candidate.analyzed":
                _staleness(e, report)
    lifecycle = check_lineage(events, now_ms, report, first_recording_ms)
    counts = defaultdict(int)
    for e in events:
        counts[f"{e['service']}:{e['event_type']}"] += 1
    ids = [e for e in events if e["event_type"] == "candidate.evaluated"]
    outcomes = defaultdict(int)                   # P1-R outcome matrix (shared vocabulary)
    for e in events:
        code = (e.get("payload") or {}).get("outcome_code")
        if code:
            outcomes[f"{e['event_type']}:{code}"] += 1
    return {
        "generated_for": dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc).isoformat(),
        "directory": os.path.abspath(directory), "records_read": len(raw), "unique_events": len(events),
        "event_counts": dict(sorted(counts.items())),
        "identity_coverage": (sum(1 for e in ids if e["subject"].get("candidate_id")) / len(ids)) if ids else None,
        "trade_lifecycle": lifecycle, "recorder_health": health,
        "outcome_codes": dict(sorted(outcomes.items())),
        "findings": report.as_dict(), "exit_code": report.worst(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default="data/evidence_v2")
    ap.add_argument("--now", help="evaluation time (ISO, default: current time)")
    ap.add_argument("--since", help="ignore events before this time (ISO)")
    ap.add_argument("--json", help="write the full report to this path")
    args = ap.parse_args(argv)
    now_ms = iso_ms(args.now) if args.now else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    result = reconcile(args.dir, now_ms, iso_ms(args.since) if args.since else None)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
    print(f"records={result['records_read']} unique={result['unique_events']} "
          f"identity_coverage={result['identity_coverage']} lifecycle={result['trade_lifecycle']}")
    for code, info in result["findings"].items():
        print(f"  [{info['severity']:8s}] {code}: {info['count']}")
    for service, h in result["recorder_health"].items():
        print(f"  recorder {service}: {h}")
    print(f"exit_code={result['exit_code']}")
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
