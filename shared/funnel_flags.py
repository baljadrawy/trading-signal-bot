"""The funnel-recording flag shared by every service (WP-B01; R6.a, R6.c, R1.f).

``FUNNEL_RECORDING`` (environment) is ``off`` (the default) or ``on``, ignoring case and surrounding
whitespace. Any other value refuses to start: ``funnel_recording_enabled`` raises RuntimeError,
so call it once at service start-up, before any I/O.

With ``on``, the services also need ``EVIDENCE_V2_ENABLED=true``. Funnel records go to the
existing evidence-v2 store: append-only daily JSONL behind a bounded in-memory queue, where a full
queue drops the event and counts it. ``on`` without that store refuses to start too
(``require_store=True``, the default). A caller that keeps its own store may pass
``require_store=False``.

``FUNNEL_MAX_RECORDS_PER_DAY`` bounds the funnel records a process emits per UTC day (the
per-cycle envelope is not counted and never suppressed). It has no default: with
``FUNNEL_RECORDING=on`` a missing, zero, negative or non-integer value refuses to start
(``funnel_recording_config``). With ``off`` it is ignored. The number is the owner's storage
budget; nothing here chooses it.

The flag is read from the environment and is not a ``shared.config.Config`` field. Every Config
field enters ``evidence_v2.compute_config_hash``, which is stamped on signals and events, so a
new field would change those bytes even with the flag off.
"""
from __future__ import annotations

import os
import re
from typing import Mapping

FUNNEL_RECORDING_ENV = "FUNNEL_RECORDING"
FUNNEL_MODES = ("off", "on")
FUNNEL_MAX_RECORDS_PER_DAY_ENV = "FUNNEL_MAX_RECORDS_PER_DAY"


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


def funnel_max_records_per_day(environ: Mapping[str, str] | None = None) -> int:
    """The required positive integer ``FUNNEL_MAX_RECORDS_PER_DAY``; anything else raises."""
    env = os.environ if environ is None else environ
    raw = env.get(FUNNEL_MAX_RECORDS_PER_DAY_ENV)
    text = str(raw).strip() if raw is not None else ""
    if not re.fullmatch(r"[0-9]+", text) or int(text) < 1:
        raise RuntimeError(f"{FUNNEL_MAX_RECORDS_PER_DAY_ENV} {raw!r} must be a positive integer when "
                           f"{FUNNEL_RECORDING_ENV}=on (owner storage budget; no default)")
    return int(text)


def funnel_recording_config(environ: Mapping[str, str] | None = None, *,
                            require_store: bool = True) -> tuple:
    """``(enabled, max_records_per_day)``. ``on`` requires the store and a valid daily cap;
    ``off`` returns ``(False, None)`` and ignores the cap. Call at start-up, before any I/O."""
    on = funnel_recording_enabled(environ, require_store=require_store)
    return (True, funnel_max_records_per_day(environ)) if on else (False, None)
