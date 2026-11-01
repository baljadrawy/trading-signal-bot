"""WP-E06 (R4.d, R7.f; PR-C14, PR-T17, CON-09): every counter and report figure names its basis,
and net-labelled counters sit beside the legacy gross counters behind PAPER_COUNTER_LABELS.

Before/after pattern: the BEFORE modules are trade_tracker/main.py and telegram/main.py at
``BASE`` (6ae70a2, before this change), loaded from git. With the flag at its default, both run
the same synthetic scenarios against the same recording fake database and must give identical
replies, messages, log lines and database calls. With the flag on, the database writes stay
identical, the only extra call is one read of trade_results, and removing the basis tags and the
net lines gives back the legacy text. No network, database or docker.
"""
from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared import cost_label_policy as cp
from shared.accounting_flags import LEGACY_FLAGS, LEGACY_LABEL_POLICY, SINGLE_COUNT_LABEL_POLICY
from shared.config import config
from wp2_service_fakes import (FIXED_NOW, REPO, FakeDB, _load_source, _with_ptb_stubs,
                               fixed_datetime, load_after_telegram, load_after_tracker, run)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

BASE = "6ae70a2"
OWNER = "424242"
FEE = 50.0 * 0.3 / 100.0
RUNTIME = dict(TRADE_AMOUNT_USDT=50.0, FEE_ROUNDTRIP_PCT=0.3, STOP_SLIPPAGE=0.001,
               MAX_OPEN_TRADES=10, RISK_CANARY_MAX_OPEN_TRADES=3, PAPER_ECONOMIC_HALT_MODE="enforce",
               EVIDENCE_V2_ENABLED=False, NOTIFICATION_TTL_HOURS=24, TELEGRAM_CHAT_ID=OWNER)


def _git_show(path: str) -> str:
    try:
        return subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=REPO, capture_output=True,
                              text=True, check=True, timeout=30).stdout
    except Exception as exc:                                     # pragma: no cover
        pytest.skip(f"pre-change source unavailable ({BASE}:{path}): {exc}")


@pytest.fixture(scope="module")
def tg_before(tmp_path_factory):
    source = _git_show("telegram/main.py")
    tmp = tmp_path_factory.mktemp("tg_before_e06")
    return _with_ptb_stubs(lambda: _load_source("tsb_e06_telegram_before", source, tmp))


@pytest.fixture(scope="module")
def tg_after():
    return load_after_telegram()


@pytest.fixture(scope="module")
def tt_before(tmp_path_factory):
    return _load_source("tsb_e06_tracker_before", _git_show("trade_tracker/main.py"),
                        tmp_path_factory.mktemp("tt_before_e06"), REPO / "trade_tracker")


@pytest.fixture(scope="module")
def tt_after():
    return load_after_tracker()


@pytest.fixture(autouse=True)
def _runtime(monkeypatch, tg_after, tt_after):
    for name, value in RUNTIME.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", False)
    monkeypatch.setattr(tt_after, "COUNTER_LABELS", False)
    monkeypatch.setattr(tt_after, "WP2_FLAGS", LEGACY_FLAGS)
    monkeypatch.setattr(tt_after, "_FUNNEL", None)


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=repr, ensure_ascii=False)


TAG = re.compile(r" \[[a-z_]+(?: · [A-Za-z0-9_]+)*\]")


def strip_labels(text: str) -> str:
    """The legacy text: basis tags removed, net-counter lines and the closed basis block dropped."""
    text = text.split("\n\n📐 ")[0]
    lines = [l for l in text.split("\n") if not l.startswith("  صافي")]
    return TAG.sub("", "\n".join(lines))


# ── 1. the registry ────────────────────────────────────────────────────────────────────────

def test_every_net_figure_names_its_cost_model_and_label_policy():
    assert cp.COUNTER_BASES
    for field, basis in cp.COUNTER_BASES.items():
        assert basis.field == field and basis.source
        if basis.basis in (cp.BASIS_GROSS, cp.BASIS_COUNT):
            assert basis.cost_model_id is None and basis.label_policy is None
            assert basis.tag() == f"[{basis.basis}]"
        else:
            assert basis.cost_model_id == "legacy_tracker_v1"
            assert basis.label_policy in (LEGACY_LABEL_POLICY, cp.POLICY_PER_ROW)
            assert basis.tag() == f"[{basis.basis} · {basis.cost_model_id} · {basis.label_policy}]"


def test_the_legacy_gross_counters_are_labelled_gross():
    for field in ("risk_management.wins", "risk_management.losses", "trade_results.result",
                  "status.wins", "status.losses", "daily.wins_losses", "stats.gross_wins_losses",
                  "evidence.trade.closed.result_label", "tracker.close_log.result"):
        assert cp.COUNTER_BASES[field].basis == cp.BASIS_GROSS
    for field in ("risk_management.daily_pnl_percent", "risk_management.consecutive_losses",
                  "stats.net_pnl", "daily.net", "trades.net", "closed_message.net"):
        assert cp.COUNTER_BASES[field].basis == cp.BASIS_NET_RECOMPUTED


@pytest.mark.parametrize("kw", [
    dict(basis="gross_before_cost", cost_model_id="legacy_tracker_v1", label_policy=None),
    dict(basis="net_stored", cost_model_id=None, label_policy=None),
    dict(basis="net_stored", cost_model_id="legacy_tracker_v1", label_policy=None),
    dict(basis="unknown", cost_model_id=None, label_policy=None),
])
def test_a_basis_without_its_labels_is_refused(kw):
    with pytest.raises(ValueError):
        cp.CounterBasis("x", source="s", **kw)


def test_every_tag_the_services_use_is_registered():
    for path in ("telegram/main.py",):
        source = (REPO / path).read_text(encoding="utf-8")
        used = set(re.findall(r"(?:_tag|counter_tag)\('([a-z_.]+)'\)", source))
        assert used and used <= set(cp.COUNTER_BASES), (path, used - set(cp.COUNTER_BASES))


@pytest.mark.parametrize("env,expected", [({}, False), ({"PAPER_COUNTER_LABELS": "off"}, False),
                                          ({"PAPER_COUNTER_LABELS": "on"}, True),
                                          ({"PAPER_COUNTER_LABELS": " ON "}, True)])
def test_flag_values(env, expected):
    assert cp.counter_labels_enabled(env) is expected


@pytest.mark.parametrize("value", ["", "yes", "1", "true", "net"])
def test_unknown_flag_values_refuse_to_start(value, tg_after, tt_after):
    env = {"PAPER_COUNTER_LABELS": value}
    with pytest.raises(RuntimeError):
        cp.counter_labels_enabled(env)
    with pytest.raises(RuntimeError):
        tg_after.configure_counter_labels(env)
    with pytest.raises(RuntimeError):
        tt_after.configure_wp2(env)
    assert tg_after.COUNTER_LABELS is False and tt_after.COUNTER_LABELS is False


def test_services_resolve_the_flag(tg_after, tt_after, monkeypatch):
    assert tg_after.configure_counter_labels({"PAPER_COUNTER_LABELS": "on"}) is True
    tt_after.configure_wp2({"PAPER_COUNTER_LABELS": "on"})
    assert tt_after.COUNTER_LABELS is True and tt_after.WP2_FLAGS == LEGACY_FLAGS
    tt_after.configure_wp2({})
    assert tt_after.COUNTER_LABELS is False


# ── 2. net counters: stratified, never pooled (R4 test 4) ──────────────────────────────────

MIXED = [{"label_policy": LEGACY_LABEL_POLICY, "economic_result": "WIN", "n": 2},
         {"label_policy": LEGACY_LABEL_POLICY, "economic_result": "LOSS", "n": 3},
         {"label_policy": LEGACY_LABEL_POLICY, "economic_result": None, "n": 1},
         {"label_policy": SINGLE_COUNT_LABEL_POLICY, "economic_result": "LOSS", "n": 1},
         {"label_policy": SINGLE_COUNT_LABEL_POLICY, "economic_result": "BREAKEVEN", "n": 4}]


def test_net_counters_are_one_stratum_per_label_policy():
    strata = cp.net_counter_strata(MIXED)
    assert [(s.label_policy, s.cost_model_id, s.wins, s.losses, s.breakeven, s.unlabelled)
            for s in strata] == [
        (LEGACY_LABEL_POLICY, "legacy_tracker_v1", 2, 3, 0, 1),
        (SINGLE_COUNT_LABEL_POLICY, "legacy_tracker_v1", 0, 1, 4, 0)]
    assert cp.net_counter_strata(list(reversed(MIXED))) == strata
    with pytest.raises(ValueError):
        cp.require_single_label_policy(strata)
    assert cp.require_single_label_policy(strata[:1]) is strata[0]
    with pytest.raises(ValueError):
        cp.require_single_label_policy(())


def test_net_counter_rows_are_validated():
    assert cp.net_counter_strata([]) == ()
    other = cp.net_counter_strata([{"label_policy": "some_future_v1", "economic_result": "WIN", "n": 1}])
    assert other[0].cost_model_id == cp.UNSPECIFIED_COST_MODEL
    with pytest.raises(ValueError):
        cp.net_counter_strata([{"label_policy": None, "economic_result": "WIN", "n": 1}])
    with pytest.raises(ValueError):
        cp.net_counter_strata([{"label_policy": LEGACY_LABEL_POLICY, "economic_result": "PUSH", "n": 1}])


def test_net_counter_sql_groups_by_policy_and_reads_only():
    sql = cp.net_counter_sql("exit_time::date = CURRENT_DATE")
    assert sql.startswith("SELECT ") and "FROM trade_results" in sql and "GROUP BY 1, 2" in sql
    assert f"COALESCE(label_policy, '{LEGACY_LABEL_POLICY}')" in sql
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER)\b", sql)


# ── 3. telegram reports: before/after ──────────────────────────────────────────────────────

class Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def update():
    msg = Msg()
    return SimpleNamespace(effective_chat=SimpleNamespace(id=OWNER),
                           effective_user=SimpleNamespace(id=OWNER, username="op"), message=msg), msg


def streak(halt=False):
    return SimpleNamespace(halt_active=halt, consecutive_losses=2, halt_threshold=5,
                           manual_recovery_required=False, open_positions=1)


def report_rules(risk, net_rows):
    return [
        ("fetch", "GROUP BY 1, 2", net_rows),
        ("fetchrow", "FROM risk_management", risk),
        ("fetchval", "symbol_whitelist", 12),
        ("fetchval", "approval_requests", 1),
        ("fetchval", "FROM active_trades WHERE status='open'", 2),
        ("fetchrow", "service_heartbeats", {"metadata": json.dumps({"price_stream": {"connected": True}})}),
        ("fetch", "optimizer_settings", [{"key": "min_score_to_signal", "value": "3"}]),
        ("fetchrow", "COUNT(*) as total", {"total": 9, "wins": 3, "losses": 5, "breakeven": 1,
                                           "gross_wins": 5, "gross_losses": 4, "avg_profit": 0.12,
                                           "sum_usdt": 1.25}),
        ("fetch", "ORDER BY exit_time DESC", [
            {"symbol": "AAAUSDT", "result": "WIN", "profit_percent": 0.2, "profit_usdt": 0.1,
             "target_reached": 1, "exit_time": FIXED_NOW, "notes": "target"},
            {"symbol": "BBBUSDT", "result": "LOSS", "profit_percent": -3.1, "profit_usdt": -1.55,
             "target_reached": 0, "exit_time": FIXED_NOW, "notes": "stop"}]),
        ("fetch", "DISTINCT ON (symbol)", [{"symbol": "CCCUSDT", "entry_price": 1.0,
                                            "highest_target_hit": 0,
                                            "opened_at": FIXED_NOW.replace(tzinfo=None)}]),
        ("fetchval", "COUNT(*) FROM signals WHERE telegram_sent", 7),
        ("fetch", "GROUP BY decision_source", []),
        ("fetchval", "='WIN'", 4),
        ("fetchval", "='LOSS'", 6),
        ("fetchrow", "COUNT(*) AS total", {"total": 3, "gross_usdt": 0.4}),
        ("fetchrow", "ORDER BY score DESC", {"symbol": "DDDUSDT", "score": 7, "claude_approved": True}),
        ("fetchval", "analysis_results", "bullish"),
        ("fetchval", "COUNT(*)", 5),
    ]


RISKS = [None, {"signals_sent": 4, "wins": 2, "losses": 5}, {"signals_sent": 0, "wins": 0, "losses": 0}]
NETS = [[], MIXED, MIXED[:2]]
COMMANDS = ("cmd_status", "cmd_stats", "cmd_trades", "cmd_performance", "cmd_daily")


def report(module, monkeypatch, command, risk, net_rows, paused=False):
    db = FakeDB(report_rules(risk, net_rows))
    monkeypatch.setattr(module, "Database", db)
    monkeypatch.setattr(module, "get_pause_state",
                        AsyncMock(return_value=(paused, "manual_pause" if paused else None)))
    monkeypatch.setattr(module, "loss_streak_state", AsyncMock(return_value=streak()))
    monkeypatch.setattr(module, "datetime", fixed_datetime())
    upd, msg = update()
    run(getattr(module, command)(upd, SimpleNamespace(args=[])))
    return msg.replies, db.log


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("case", range(len(RISKS) * len(NETS) * 2))
def test_reports_are_byte_identical_with_the_flag_off(command, case, tg_before, tg_after, monkeypatch):
    risk, net_rows, paused = RISKS[case % 3], NETS[(case // 3) % 3], bool(case // 9)
    ref = report(tg_before, monkeypatch, command, risk, net_rows, paused)
    assert ref[0]
    assert canon(report(tg_after, monkeypatch, command, risk, net_rows, paused)) == canon(ref)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("case", range(len(RISKS) * len(NETS)))
def test_labels_on_only_add_tags_and_net_counters(command, case, tg_before, tg_after, monkeypatch):
    risk, net_rows = RISKS[case % 3], NETS[case // 3]
    ref_text, ref_log = report(tg_before, monkeypatch, command, risk, net_rows)
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", True)
    text, log = report(tg_after, monkeypatch, command, risk, net_rows)
    assert len(text) == 1 and text != ref_text
    assert strip_labels(text[0]) == ref_text[0]
    extra = [entry for entry in log if "GROUP BY 1, 2" in entry[1]]
    assert [entry for entry in log if entry not in extra] == ref_log      # the legacy calls, in order
    if command in ("cmd_status", "cmd_stats", "cmd_daily"):
        assert len(extra) == 1 and extra[0][0] == "fetch" and extra[0][2] == (FEE,)
        assert all(not re.search(r"\b(INSERT|UPDATE|DELETE)\b", e[1]) for e in extra)
        lines = [l for l in text[0].split("\n") if l.startswith("  صافي")]
        assert len(lines) == max(1, len({r["label_policy"] for r in net_rows}))    # never pooled
    else:
        assert extra == []


def test_status_labels_the_gross_counters_and_shows_net_beside_them(tg_after, monkeypatch):
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", True)
    (text,), _ = report(tg_after, monkeypatch, "cmd_status", RISKS[1], MIXED)
    assert "إغلاقات رابحة [gross_before_cost]: 2" in text
    assert "إغلاقات خاسرة [gross_before_cost]: 5" in text
    assert (f"صافي [net_stored_else_recomputed · legacy_tracker_v1 · {LEGACY_LABEL_POLICY}]: "
            "2 ربح / 3 خسارة / 0 تعادل / 1 بلا تصنيف") in text
    assert (f"صافي [net_stored_else_recomputed · legacy_tracker_v1 · {SINGLE_COUNT_LABEL_POLICY}]: "
            "0 ربح / 1 خسارة / 4 تعادل") in text


def test_stats_names_every_basis(tg_after, monkeypatch):
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", True)
    (text,), _ = report(tg_after, monkeypatch, "cmd_stats", RISKS[1], MIXED[:2])
    assert text.count("[net_stored_else_recomputed · legacy_tracker_v1 · per_row_label_policy]") == 3
    assert "خسارة) [gross_before_cost]" in text
    assert text.count(f"[net_recomputed_flat · legacy_tracker_v1 · {LEGACY_LABEL_POLICY}]") == 2


# ── 4. the closed lifecycle message ────────────────────────────────────────────────────────

CLOSED_ROWS = [
    {"id": 9, "symbol": "AAAUSDT", "entry_price": 100.0, "exit_price": 100.2, "notes": "expired",
     "result": "WIN", "target_reached": 0, "duration_hours": 4.0, "profit_percent": 0.2,
     "profit_usdt": 0.1, "cost_usdt": FEE, "net_profit_usdt": 0.1 - FEE,
     "economic_result": "LOSS", "label_policy": LEGACY_LABEL_POLICY},
    {"id": 10, "symbol": "BBBUSDT", "entry_price": 100.0, "exit_price": 102.0, "notes": "target",
     "result": "WIN", "target_reached": 1, "duration_hours": 2.0, "profit_percent": 2.0,
     "profit_usdt": 1.0, "cost_usdt": 0.1, "net_profit_usdt": 0.9,
     "economic_result": "WIN", "label_policy": SINGLE_COUNT_LABEL_POLICY},
    {"id": 11, "symbol": "CCCUSDT", "entry_price": 100.0, "exit_price": 97.0, "notes": "stop",
     "result": "LOSS", "target_reached": 0, "duration_hours": 1.0, "profit_percent": -3.1,
     "profit_usdt": -1.55, "cost_usdt": None, "net_profit_usdt": None,
     "economic_result": None, "label_policy": None},
]


def deliver(module, monkeypatch, row):
    db = FakeDB([("fetchrow", "FROM trade_results tr", row), ("fetch", "trade_target_fills", [])])
    event = {"id": 77, "payload": {"trade_result_id": row["id"], "active_trade_id": 5},
             "created_at": None, "deferrals": 0}

    async def claim(event_type, owner, limit=20):
        return [event] if event_type == "trade.closed" else []

    sent, acks = [], []

    async def send_message(chat_id, text):
        sent.append(text)

    async def ack(*a):
        acks.append(a)

    monkeypatch.setattr(module, "Database", db)
    monkeypatch.setattr(module, "claim", claim)
    monkeypatch.setattr(module, "ack", ack)
    n = run(module.deliver_trade_lifecycle_events(SimpleNamespace(send_message=send_message), "w1"))
    return n, sent, acks, db.log


@pytest.mark.parametrize("index", range(len(CLOSED_ROWS)))
def test_closed_message_is_identical_off_and_labelled_on(index, tg_before, tg_after, monkeypatch):
    row = CLOSED_ROWS[index]
    ref = deliver(tg_before, monkeypatch, row)
    assert canon(deliver(tg_after, monkeypatch, row)) == canon(ref)
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", True)
    n, sent, acks, log = deliver(tg_after, monkeypatch, row)
    assert (n, acks, log) == ref[0:1] + ref[2:]
    assert sent[0].startswith(ref[1][0]) and strip_labels(sent[0]) == ref[1][0]
    block = sent[0][len(ref[1][0]):]
    assert "[gross_before_cost]" in block
    assert f"[net_recomputed_flat · legacy_tracker_v1 · {LEGACY_LABEL_POLICY}]" in block
    if row["label_policy"]:
        assert f"المخزَّن: {row['economic_result']}" in block
        assert f"[net_stored · legacy_tracker_v1 · {row['label_policy']}]" in block
    else:
        assert "المخزَّن" not in block


# ── 5. the tracker close: gross counter unchanged, net label beside it (PR-T17) ─────────────

class Log:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda msg, *a, **k: self.lines.append((level, msg % a if a else msg))


def close(module, monkeypatch, profit_usdt, inserted=555):
    db = FakeDB([("fetch", "trade_target_fills", []), ("fetchval", "INSERT INTO trade_results", inserted)])
    log, outbox = Log(), []

    async def enqueue(conn, event_type, aggregate_type, aggregate_id, payload):
        outbox.append((event_type, aggregate_type, aggregate_id, canon(payload)))

    for name, value in (("Database", db), ("enqueue", enqueue), ("logger", log),
                        ("datetime", fixed_datetime()),
                        ("assess_new_trade_risk", AsyncMock(return_value="decision")),
                        ("record_risk_decision", AsyncMock())):
        monkeypatch.setattr(module, name, value)
    module._closing.clear()
    trade = {"id": 3, "signal_id": 30, "symbol": "TTTUSDT", "entry_price": 100.0,
             "remaining_fraction": 1.0, "realized_profit_percent": 0.0, "realized_profit_usdt": 0.0,
             "opened_at": FIXED_NOW.replace(tzinfo=None), "timeframe": "4h", "stop_loss": 97.0}
    exit_price = 100.0 * (1 + profit_usdt / 50.0)
    run(module.close_trade_barrier(trade, "X", profit_usdt / 50.0 * 100, profit_usdt, exit_price,
                                   "expired", 0, False))
    return db.log, outbox, log.lines


# 0 < gross < cost, gross == cost, gross < 0, gross > cost, gross == 0
PROFITS = (0.1, FEE, -1.55, 1.0, 0.0)


@pytest.mark.parametrize("profit", PROFITS)
@pytest.mark.parametrize("inserted", (555, None))
def test_tracker_close_is_byte_identical_off(profit, inserted, tt_before, tt_after, monkeypatch):
    ref = close(tt_before, monkeypatch, profit, inserted)
    assert canon(close(tt_after, monkeypatch, profit, inserted)) == canon(ref)


@pytest.mark.parametrize("profit,gross_column,net_label", [
    (0.1, "wins", "LOSS"), (FEE, "wins", "BREAKEVEN"), (-1.55, "losses", "LOSS"),
    (1.0, "wins", "WIN"), (0.0, "losses", "LOSS")])
def test_tracker_labels_on_log_the_net_label_beside_the_gross_counter(
        profit, gross_column, net_label, tt_before, tt_after, monkeypatch):
    ref_db, ref_outbox, ref_lines = close(tt_before, monkeypatch, profit)
    monkeypatch.setattr(tt_after, "COUNTER_LABELS", True)
    db, outbox, lines = close(tt_after, monkeypatch, profit)
    assert canon((db, outbox)) == canon((ref_db, ref_outbox))          # writes unchanged
    extra = [l for l in lines if l not in ref_lines]
    assert [l for l in lines if l not in extra] == ref_lines and len(extra) == 1
    increments = [e for e in db if "INSERT INTO risk_management" in e[1]]
    assert len(increments) == 1 and f"(date, {gross_column})" in increments[0][1]
    assert extra[0] == ("info", f"counter basis: risk_management.{gross_column} +1 [gross_before_cost] "
                                f"| net {net_label} [net_stored · legacy_tracker_v1 · "
                                f"{LEGACY_LABEL_POLICY}] (trade_results.economic_result)")


def test_tracker_labels_on_log_nothing_for_a_duplicate_close(tt_before, tt_after, monkeypatch):
    ref = close(tt_before, monkeypatch, 0.1, None)
    monkeypatch.setattr(tt_after, "COUNTER_LABELS", True)
    assert canon(close(tt_after, monkeypatch, 0.1, None)) == canon(ref)


def test_tracker_counter_log_failure_never_changes_the_close(tt_before, tt_after, monkeypatch):
    ref_db, ref_outbox, _ = close(tt_before, monkeypatch, 0.1)
    monkeypatch.setattr(tt_after, "COUNTER_LABELS", True)
    monkeypatch.setattr(tt_after.cost_policy, "close_counter_log",
                        lambda *a: (_ for _ in ()).throw(KeyError("label_policy")))
    db, outbox, lines = close(tt_after, monkeypatch, 0.1)
    assert canon((db, outbox)) == canon((ref_db, ref_outbox))
    assert any(level == "error" and "counter-basis log failed" in msg for level, msg in lines)


@pytest.mark.parametrize("policy", [LEGACY_LABEL_POLICY, SINGLE_COUNT_LABEL_POLICY])
def test_close_counter_log_names_the_row_policy(policy):
    line = cp.close_counter_log(0.1, {"economic_result": "LOSS", "label_policy": policy})
    assert line.endswith(f"net LOSS [net_stored · legacy_tracker_v1 · {policy}] "
                         "(trade_results.economic_result)")
    assert "risk_management.wins +1 [gross_before_cost]" in line


def test_a_failed_net_read_never_breaks_the_report(tg_before, tg_after, monkeypatch):
    ref_text, _ = report(tg_before, monkeypatch, "cmd_status", RISKS[1], MIXED)
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", True)
    (text,), _ = report(tg_after, monkeypatch, "cmd_status", RISKS[1],
                        lambda *a: (_ for _ in ()).throw(ConnectionError("db")))
    assert "صافي: غير متاح [net_stored_else_recomputed" in text
    assert strip_labels(text) == ref_text[0]


def test_a_bad_stored_row_never_blocks_the_closed_notification(tg_before, tg_after, monkeypatch):
    row = dict(CLOSED_ROWS[0], net_profit_usdt="not-a-number")
    ref = deliver(tg_before, monkeypatch, row)
    monkeypatch.setattr(tg_after, "COUNTER_LABELS", True)
    assert canon(deliver(tg_after, monkeypatch, row)) == canon(ref)
