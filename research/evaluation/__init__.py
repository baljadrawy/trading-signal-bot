"""A45-G evaluation tooling (research only; production never imports this package).

* ``net_eval``  (``a45g-ne-v1``): cost- and turnover-aware net evaluation of a trade population, with
  per-component cost attribution (fee / spread / slippage), break-even edge, cost stress, drawdown,
  day-clustered uncertainty and concentration checks.
* ``regimes``   (``a45g-rg-v1``): causal (closed-candle, no look-ahead) regime labels, an as-of join
  from regimes to trades, and a seeded synthetic regime-switching market for engine tests.

Evidence class: engineering and synthetic only. ``net_eval`` refuses to label a result unless the data
permission is the synthetic marker or a recorded, licence-cleared, holdout-excluding
``research.mechanisms.simulate.DatasetPermission`` plus an owner authorization reference. Today no
real dataset has such a record (docs/governance/DEVELOPMENT_FIRST_POLICY.md section 2, D1 row).
Nothing here produces, implies or estimates an edge.
"""
VERSION = "a45g-eval-v1"
