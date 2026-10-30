"""Design A v1.0: BTC/USDT weekly SMA200 long/cash (research only, never imported by production).

Pure, offline and inactive. ``decision.decide(state, snapshot)`` takes the weekly decision;
``ledger.apply_decision`` records it and opens a pending transition only for a genuine change of
position; ``ledger.execute_pending`` fills that transition at the Tuesday open reference (or a
deferral candle within three calendar days) with the frozen cost model, or cancels it. All money
and quantities are ``Decimal``; all instants are UTC.

Evidence class: synthetic only. ``state.Snapshot`` accepts nothing but the synthetic
``DatasetPermission``, no real dataset is permitted, and nothing here says whether the rule earns
money. See docs/strategy/DESIGN_A_SPEC_v1.0.md.
"""
VERSION = "design-a-v1.0"
