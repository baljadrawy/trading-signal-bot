"""Signal readiness contract (CR-1 / Option 3 — claude_review retired from the active path).

Producer: signal_engine.save_signal() INSERTs the signals row with
decision_source=READY_DECISION_SOURCE and enqueues SIGNAL_READY_EVENT in the SAME
transaction, so either both exist or neither does.

Meaning of SIGNAL_READY_EVENT: the signal finished every required non-Claude step
and is eligible for downstream handling. It is NOT a trade-open permission: the
telegram pause/B3 delivery gate and the trade_tracker risk guard still decide.

claude_approved is deliberately left NULL for new signals (no fake Claude
approval). Legacy rows/events (decision_source 'policy_auto'/'claude' with
claude_approved=true, event 'signal.reviewed') stay valid so in-flight events and
a rollback to claude_review keep working.

This module must stay free of Claude/Anthropic and python-telegram-bot imports.
"""
import math
from typing import Any, Mapping, Optional

SIGNAL_READY_EVENT = 'signal.ready'
LEGACY_SIGNAL_REVIEWED_EVENT = 'signal.reviewed'
# Fits signals.decision_source VARCHAR(32).
READY_DECISION_SOURCE = 'policy_ready'

# Readiness predicate for SQL over `signals s`. Always TRUE/FALSE (never NULL), so
# it is safe both in WHERE and under NOT (a NULL here would silently flip
# "terminal" checks into "retry later"). Semantically:
#   (s.decision_source = 'policy_ready' OR s.claude_approved = true)
READY_SQL_PREDICATE = (
    f"(s.decision_source IS NOT DISTINCT FROM '{READY_DECISION_SOURCE}' "
    f"OR s.claude_approved IS TRUE)")

REQUIRED_NUMERIC_FIELDS = (
    'entry_price', 'target_1', 'target_2', 'target_3', 'stop_loss', 'total_score')


def assert_signal_complete(signal: Mapping[str, Any]) -> None:
    """Fail closed before the transaction: an incomplete signal is never saved/ready."""
    if not signal.get('symbol'):
        raise ValueError('signal missing symbol')
    for key in REQUIRED_NUMERIC_FIELDS:
        value = signal.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f'signal field {key} is not numeric: {value!r}') from None
        if not math.isfinite(number):
            raise ValueError(f'signal field {key} is not finite: {value!r}')
        if key != 'total_score' and number <= 0:
            raise ValueError(f'signal field {key} must be > 0: {value!r}')


def ready_payload(signal_id: int, strategy_version: str) -> dict:
    return {'signal_id': signal_id, 'decision_source': READY_DECISION_SOURCE,
            'strategy_version': strategy_version}


def _get(row: Optional[Mapping[str, Any]], key: str):
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def is_ready_row(row: Optional[Mapping[str, Any]]) -> bool:
    """Python twin of READY_SQL_PREDICATE (used for display)."""
    return (_get(row, 'decision_source') == READY_DECISION_SOURCE
            or _get(row, 'claude_approved') is True)


def is_deliverable_for_event(event_type: str, signal: Optional[Mapping[str, Any]]) -> bool:
    """Per-event readiness gate for the telegram consumer.

    signal.ready    -> decision_source must be READY_DECISION_SOURCE
    signal.reviewed -> legacy gate: claude_approved must be exactly True
    anything else   -> never deliverable
    Already-sent signals are never deliverable (dedupe across both events).
    """
    if signal is None or _get(signal, 'telegram_sent'):
        return False
    if event_type == SIGNAL_READY_EVENT:
        return _get(signal, 'decision_source') == READY_DECISION_SOURCE
    if event_type == LEGACY_SIGNAL_REVIEWED_EVENT:
        return _get(signal, 'claude_approved') is True
    return False


# ---- statistics labels (Arabic UI) -------------------------------------------------
DECISION_CATEGORY_LABELS = {
    'policy_ready': '🟢 جاهزة بالسياسة الآلية (policy_ready)',
    'policy_auto': '🔁 سياسة آلية عبر المرحِّل القديم (policy_auto)',
    'claude_approved': '🤖 مراجعة Claude قديمة — قبول',
    'claude_rejected': '🤖 مراجعة Claude قديمة — رفض',
    'fail_closed': '🧯 رفض أمان عند فشل المراجعة القديمة',
    'legacy_approved': '📦 قبول قديم (مصدر غير محدد)',
    'legacy_rejected': '📦 رفض قديم (مصدر غير محدد)',
    'not_ready': '⏳ غير جاهزة / لم تكتمل',
}
DECISION_CATEGORY_ORDER = tuple(DECISION_CATEGORY_LABELS)


def decision_category(decision_source: Optional[str], claude_approved: Optional[bool]) -> str:
    if decision_source == READY_DECISION_SOURCE:
        return 'policy_ready'
    if decision_source == 'system_fail_closed':
        return 'fail_closed'
    if decision_source == 'policy_auto' and claude_approved is True:
        return 'policy_auto'
    if decision_source == 'claude':
        if claude_approved is True:
            return 'claude_approved'
        if claude_approved is False:
            return 'claude_rejected'
    if claude_approved is True:
        return 'legacy_approved'
    if claude_approved is False:
        return 'legacy_rejected'
    return 'not_ready'


def decision_label(decision_source: Optional[str], claude_approved: Optional[bool]) -> str:
    return DECISION_CATEGORY_LABELS[decision_category(decision_source, claude_approved)]


def decision_breakdown(rows) -> dict:
    """rows: iterable of {decision_source, claude_approved, n} -> {category: count}."""
    counts = {key: 0 for key in DECISION_CATEGORY_ORDER}
    for row in rows:
        counts[decision_category(row['decision_source'], row['claude_approved'])] += int(row['n'] or 0)
    return counts


def decision_breakdown_lines(counts: Mapping[str, int], total: int, indent: str = '  ') -> list:
    lines = []
    for key in DECISION_CATEGORY_ORDER:
        n = int(counts.get(key) or 0)
        if not n:
            continue
        pct = f' ({n / total * 100:.1f}%)' if total else ''
        lines.append(f'{indent}{DECISION_CATEGORY_LABELS[key]}: {n}{pct}')
    if not lines:
        lines.append(f'{indent}لا توجد بيانات بعد')
    return lines
