"""The funnel-recording flag shared by every service (WP-B01; R6.a, R6.c, R1.f).

``FUNNEL_RECORDING`` (environment) is ``off`` (the default) or ``on``, ignoring case and surrounding
whitespace. Any other value refuses to start: ``funnel_recording_enabled`` raises RuntimeError,
so call it once at service start-up, before any I/O.

With ``on``, the services also need ``EVIDENCE_V2_ENABLED=true``. Funnel records go to the
existing evidence-v2 store: append-only daily JSONL behind a bounded in-memory queue, where a full
queue drops the event and counts it. ``on`` without that store refuses to start too
(``require_store=True``, the default). A caller that keeps its own store may pass
``require_store=False``.

The flag is read from the environment and is not a ``shared.config.Config`` field. Every Config
field enters ``evidence_v2.compute_config_hash``, which is stamped on signals and events, so a
new field would change those bytes even with the flag off.
"""
from __future__ import annotations

import os
from typing import Mapping

FUNNEL_RECORDING_ENV = "FUNNEL_RECORDING"
FUNNEL_MODES = ("off", "on")


def funnel_recording_mode(environ: Mapping[str, str] | None = None) -> str:
    """``'off'`` or ``'on'``; an unknown value raises RuntimeError (fail closed at start-up)."""
    env = os.environ if environ is None else environ
    raw = env.get(FUNNEL_RECORDING_ENV, "off")
    mode = str(raw).strip().lower()
    if mode not in FUNNEL_MODES:
        raise RuntimeError(f"unknown {FUNNEL_RECORDING_ENV} {raw!r}; expected one of {FUNNEL_MODES}")
    return mode


def funnel_recording_enabled(environ: Mapping[str, str] | None = None, *,
                             require_store: bool = True) -> bool:
    """True only for ``on``. With ``require_store``, ``on`` also needs EVIDENCE_V2_ENABLED=true."""
    on = funnel_recording_mode(environ) == "on"
    if on and require_store:
        from shared import evidence_v2
        if not evidence_v2.enabled():
            raise RuntimeError(f"{FUNNEL_RECORDING_ENV}=on needs EVIDENCE_V2_ENABLED=true "
                               "(the funnel records use the evidence-v2 bounded store)")
    return on
