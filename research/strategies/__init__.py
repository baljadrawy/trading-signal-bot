"""Strategy candidate modules for research (never imported by production).

Pure, standard-library-only implementations of registered hypotheses (docs/strategy/HYPOTHESIS_REGISTER.md).
They reuse the s4-mech-v1 cost model (``research.mechanisms.costs``) and data-permission gate
(``research.mechanisms.simulate.DatasetPermission``).

Evidence class: engineering and synthetic only. Nothing here produces or implies an edge; running a module on real
data is a governed research action (see docs/strategy/NEXT_LICENSED_DATA_STEP.md).
"""
