#!/usr/bin/env python
"""Canary Phase A watchdog — self-contained (no repo-branch dependency).
Reads the live recorder telemetry window, computes a single state, and sends ONE
identified Telegram alert on RED/INVALID transitions (deduped). Run by cron.

States: GREEN (ok) / YELLOW (criteria miss, no rollback) / RED (rollback trigger) /
INVALID (captured==0 for >12h => sample too sparse) / STALE (recorder not updating).
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

REPO = "/home/tradmin/trading-signal-bot"
TEL = f"{REPO}/data/evidence/_telemetry.json"
STATE_FILE = "/home/tradmin/.canary_watchdog_state"
INVALID_HOURS = 12.0
STALE_SECONDS = 600          # telemetry older than 10min => recorder not updating
LAT_MAX_MS = 1.0
WSR_MIN = 0.999
FILTER_DESC = "BTCUSDT / 15m,4h,1d / live"


def env(key):
    try:
        for ln in open(f"{REPO}/.env"):
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1]
    except Exception:
        pass
    return None


def started_epoch():
    try:
        out = subprocess.check_output(
            ["docker", "inspect", "trading_signal_engine", "--format", "{{.State.StartedAt}}"],
            stderr=subprocess.DEVNULL, timeout=15).decode().strip()
        out = out.split(".")[0].rstrip("Z")
        d = dt.datetime.strptime(out, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def worst(history):
    p95 = max((s.get("evidence_capture_latency_ms_p95") or 0.0) for s in history)
    dropped = max((s.get("evidence_dropped_records") or 0) for s in history)
    wsr = min((s.get("evidence_write_success_rate", 1.0)) for s in history)
    pending = max((s.get("evidence_pending_records_on_shutdown") or 0) for s in history)
    return p95, dropped, wsr, pending


def send_telegram(text):
    tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=10)
        return True
    except Exception:
        return False


def build_msg(state, reason, latest, hours, n):
    action = ""
    if state == "RED":
        action = "\n⚠️ تراجع موصى: أبلغ المالك واتبع docs/ops/COMPOSE_OPERATIONS.md (لا تنفّذ أوامر Compose تلقائياً)"
    elif state == "INVALID":
        action = "\n⚠️ عيّنة غير صالحة (BTCUSDT شحيح) — أعد ضبط النطاق، لا تنتظر 48h"
    elif state == "STALE":
        action = "\n⚠️ التيليمتري متوقّف — المُسجِّل لا يحدّث (rollback/crash؟)"
    return (
        f"🐤 CANARY PHASE A — Signal Bot  [{state}]\n"
        f"الفلتر: {FILTER_DESC}\n"
        f"captured={latest.get('evidence_captured_total')} "
        f"filtered={latest.get('evidence_filtered_records')} "
        f"dropped={latest.get('evidence_dropped_records')}\n"
        f"write_success={latest.get('evidence_write_success_rate',1.0)*100:.1f}% "
        f"p95={latest.get('evidence_capture_latency_ms_p95')}ms "
        f"pending={latest.get('evidence_pending_records_on_shutdown')}\n"
        f"uptime={hours:.1f}h | window={n} snapshots\n"
        f"السبب: {reason}{action}\n"
        f"المصدر: canary_watchdog @ integration/research-pipeline (الخادم)")


def compute():
    if not os.path.exists(TEL):
        return "STALE", "no telemetry file", {}, 0.0, 0
    data = json.load(open(TEL))
    history = data if isinstance(data, list) else [data]
    history = [s for s in history if isinstance(s, dict)]
    if not history:
        return "STALE", "empty telemetry", {}, 0.0, 0
    latest = history[-1]
    age = time.time() - latest.get("ts", 0)
    started = started_epoch()
    hours = (time.time() - started) / 3600 if started else 0.0
    captured = latest.get("evidence_captured_total", 0)
    if age > STALE_SECONDS:
        return "STALE", f"telemetry {age/60:.0f}min old", latest, hours, len(history)
    p95, dropped, wsr, pending = worst(history)
    if captured == 0 and started and hours >= INVALID_HOURS:
        return "INVALID", f"captured=0 after {hours:.1f}h", latest, hours, len(history)
    reasons = []
    rollback = False
    if dropped > 0:
        reasons.append(f"dropped={dropped}"); rollback = True
    if wsr < WSR_MIN:
        reasons.append(f"write_success={wsr*100:.2f}%"); rollback = True
    if p95 >= LAT_MAX_MS:
        reasons.append(f"p95={p95}ms")
    if pending > 0:
        reasons.append(f"pending={pending}")
    if rollback:
        return "RED", "; ".join(reasons), latest, hours, len(history)
    if reasons:
        return "YELLOW", "; ".join(reasons), latest, hours, len(history)
    return "GREEN", "ok", latest, hours, len(history)


VALIDATED_FILE = "/home/tradmin/.canary_validated"


def main():
    force_init = "--init" in sys.argv
    state, reason, latest, hours, n = compute()
    msg = build_msg(state, reason, latest, hours, n)
    prev = ""
    if os.path.exists(STATE_FILE):
        prev = open(STATE_FILE).read().strip()

    # SUCCESS milestone: first time the write path is exercised end-to-end
    captured = latest.get("evidence_captured_total", 0) or 0
    flushed = latest.get("evidence_flushed_total", 0) or 0
    if captured > 0 and flushed > 0 and not os.path.exists(VALIDATED_FILE):
        vm = ("✅ CANARY VALIDATED — مسار الكتابة عمل (capture→queue→flush→sink)\n" + msg)
        print(f"validated_telegram_sent={send_telegram(vm)}")
        open(VALIDATED_FILE, "w").write(f"captured={captured} flushed={flushed}")

    # alert on RED/INVALID transitions, or a forced init confirmation
    if force_init or (state in ("RED", "INVALID") and prev != state):
        sent = send_telegram(("✅ مراقبة الـCanary فعّالة\n" + msg) if force_init else msg)
        print(f"telegram_sent={sent}")
    open(STATE_FILE, "w").write(state)
    print(f"{state} | {reason} | captured={latest.get('evidence_captured_total')} "
          f"filtered={latest.get('evidence_filtered_records')} uptime={hours:.1f}h")


if __name__ == "__main__":
    main()
