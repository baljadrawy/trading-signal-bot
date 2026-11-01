"""WP-E09 (R4.c, OQ-08; DFP:L61): the runtime legacy_tracker_v1 cost next to the PROPOSED research
0.40% and 0.60% models on synthetic trades, every figure under its cost_model_id and label_policy,
never pooled, and never wired into a live report. Synthetic legs only; no I/O beyond the sources
checked for wiring.
"""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from shared import cost_label_policy as cp
from shared import cost_models as cm
from shared.cost_models import Leg, LegacyTrackerV1

REPO = Path(__file__).resolve().parent.parent
IDS = ("legacy_tracker_v1", "research_baseline_v1", "research_stress_v1")
LEGACY = LegacyTrackerV1(fee_roundtrip_pct=0.3, stop_slippage=0.001, configured_notional_usdt=100.0)


def entry(price="100"):
    return Leg("entry", "entry", D(1), D(price), True)


TRADES = {
    "stop": [entry(), Leg("x", "stop", D(1), D(97), True)],
    "targets": [entry(), Leg("t1", "target", D("0.5"), D(102), False),
                Leg("t2", "target", D("0.5"), D(104), False)],
    "tiny": [entry(), Leg("x", "time_exit", D(1), D("100.2"), True)],      # 0 < gross < cost
}


@pytest.fixture(scope="module")
def report():
    return cp.side_by_side_report(TRADES, legacy=LEGACY, evidence_class="synthetic")


def test_one_column_per_model_each_labelled(report):
    assert set(report["columns"]) == set(IDS)
    for cost_model_id, column in report["columns"].items():
        model = cm.get_cost_model(cost_model_id)
        assert column["cost_model_id"] == cost_model_id
        assert column["label_policy"] == model.label_policy
        assert column["model_status"] == model.status
        assert column["round_trip_pct"] == model.round_trip_pct
        assert column["content_hash"] == model.content_hash
        assert column["trades"] == len(TRADES)
    assert report["columns"]["legacy_tracker_v1"]["label_policy"] == "net_after_modeled_cost_v1"
    assert report["columns"]["legacy_tracker_v1"]["model_status"] == "LEGACY_RUNTIME_RULE"
    for rid in IDS[1:]:
        assert report["columns"][rid]["model_status"] == "PROPOSED_NOT_ADOPTED"
        assert report["columns"][rid]["label_policy"] == cm.UNSPECIFIED     # OQ-08: an owner decision
    assert [report["columns"][i]["round_trip_pct"] for i in IDS] == ["0.3", "0.40", "0.60"]


def test_never_pooled(report):
    assert report["pooled"] is False and report["not_profitability_evidence"] is True
    assert report["evidence_class"] == "synthetic"
    assert set(report) == {"scheme", "evidence_class", "not_profitability_evidence", "pooled",
                           "binding", "gross", "columns"}
    lines = cp.render_side_by_side(report)
    assert len(lines) == 2 + len(IDS)
    for line, cost_model_id in zip(lines[2:], IDS):
        assert line.startswith(f"[{cost_model_id} · {report['columns'][cost_model_id]['label_policy']} · ")
        assert all(other not in line for other in IDS if other != cost_model_id)
    books = []
    for cost_model_id, pricer in (("legacy_tracker_v1", LEGACY),
                                  ("research_baseline_v1", cm.ResearchPricer("research_baseline_v1"))):
        book = cm.CostBook(pricer, position_id=f"p-{cost_model_id}")
        for leg in TRADES["stop"]:
            book.book(leg)
        books.append(book.close())
    with pytest.raises(cm.CostModelError):
        cm.aggregate(books)


def test_stop_exit_figures(report):
    legacy = report["columns"]["legacy_tracker_v1"]["per_trade"]["stop"]
    # legacy: the stop fills at 97 × (1 − 0.001) and the flat 0.3% of the configured 100 is added
    assert legacy["net_pnl"] == D(97) * (1 - D("0.001")) - 100 - D("0.3")
    assert report["columns"]["legacy_tracker_v1"]["double_counted_kinds"] == ["slippage"]
    for rid, a in (("research_baseline_v1", D("0.001")), ("research_stress_v1", D("0.002"))):
        buy, sell = D(100) * (1 + a), D(97) * (1 - a)
        net = sell - buy - D("0.001") * (buy + sell)
        assert report["columns"][rid]["per_trade"]["stop"]["net_pnl"] == net
        assert report["columns"][rid]["double_counted_kinds"] == []


def test_gross_is_model_independent_and_labelled(report):
    g = report["gross"]
    assert g["basis"] == "gross_before_cost" and g["trades"] == 3
    assert g["gross_reference_pnl"] == D(-3) + D(3) + D("0.2")
    assert (g["gross_wins"], g["gross_losses"]) == (2, 1)
    for column in report["columns"].values():
        assert {p: v["gross_reference_pnl"] for p, v in column["per_trade"].items()} == {
            "stop": D(-3), "targets": D(3), "tiny": D("0.2")}


def test_con09_small_gross_win_is_a_net_loss_under_every_model(report):
    for cost_model_id in IDS:
        column = report["columns"][cost_model_id]
        assert column["per_trade"]["tiny"]["net_label"] == "LOSS"
        assert (column["net_wins"], column["net_losses"], column["net_breakeven"]) == (1, 2, 0)


def test_totals_are_per_model_sums(report):
    for column in report["columns"].values():
        assert column["net_pnl"] == sum((v["net_pnl"] for v in column["per_trade"].values()), D(0))
    nets = [report["columns"][i]["net_pnl"] for i in IDS]
    assert nets[2] < nets[1]                                      # stress costs more than baseline


def test_deterministic_and_order_independent(report):
    again = cp.side_by_side_report(dict(reversed(list(TRADES.items()))), legacy=LEGACY,
                                   evidence_class="synthetic")
    assert again == report
    assert cp.render_side_by_side(again) == cp.render_side_by_side(report)


@pytest.mark.parametrize("evidence_class", ["engineering", "exploratory", "prospective",
                                            "confirmatory", "", None])
def test_only_synthetic_trades_are_accepted(evidence_class):
    with pytest.raises(ValueError):
        cp.side_by_side_report(TRADES, legacy=LEGACY, evidence_class=evidence_class)


def test_inputs_are_required():
    with pytest.raises(ValueError):
        cp.side_by_side_report({}, legacy=LEGACY, evidence_class="synthetic")
    with pytest.raises(TypeError):
        cp.side_by_side_report(TRADES, legacy=cm.ResearchPricer("research_baseline_v1"),
                               evidence_class="synthetic")
    with pytest.raises(TypeError):
        cp.side_by_side_report(TRADES, evidence_class="synthetic")          # no default binding


def test_maker_stop_is_refused_by_the_research_models():
    bad = {"p": [entry(), Leg("x", "stop", D(1), D(97), False)]}
    with pytest.raises(cm.CostModelError):
        cp.side_by_side_report(bad, legacy=LEGACY, evidence_class="synthetic")


def test_the_report_is_not_wired_into_any_service():
    services = ["telegram/main.py", "trade_tracker/main.py"] + [
        str(p.relative_to(REPO)) for d in ("scanner", "analyzer", "signal_engine")
        for p in sorted((REPO / d).glob("*.py"))]
    for path in services:
        source = (REPO / path).read_text(encoding="utf-8")
        assert "side_by_side_report" not in source and "render_side_by_side" not in source, path
