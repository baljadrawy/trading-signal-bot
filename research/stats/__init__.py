"""R2 variant / alpha ledger and multiple-testing statistics (research only, never imported by production).

Pure, standard-library-only building blocks:

* ``variant_ledger``   append-only, hash-chained JSONL record of every variant tried, per family;
* ``sharpe_deflation`` Probabilistic and Deflated Sharpe Ratio (Bailey & Lopez de Prado);
* ``familywise``       Holm and Romano-Wolf stepdown family-wise adjustments;
* ``alpha_budget``     owner-governed alpha budgets (governed admissions, exploratory families).

Evidence class: engineering and synthetic only. The repository holds no real ledger and no real results.
Using this on real data is a governed research action (owner/scientific authorization plus preregistration).
See docs/strategy/VARIANT_LEDGER.md.
"""
VERSION = "r2-vledger-v1"
