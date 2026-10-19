"""S4 mechanism research infrastructure (research only, never imported by production).

Pure, stdlib-only building blocks for comparing strategy *mechanisms* before any data is used:
a conservative cost model, decision-time signal rules and a daily portfolio accountant.

Evidence class: engineering and synthetic only. Nothing here produces or implies an edge.
``simulate.run`` refuses any input that is not declared synthetic or not covered by a
recorded, licence-cleared, holdout-excluding dataset permission (``DatasetPermission``).
See docs/strategy/S4_MECHANISM_COMPARISON.md.
"""
VERSION = "s4-mech-v1"
