"""WP2 signal-integrity primitives (R3; lane C) — pure, deterministic, dormant; no production caller.

A43/A44 (``shared/signal_identity.py``) already provide the candle-anchored setup key, the
insert-once ledger, the one-bar freshness rule and the ``SIGNAL_INTEGRITY_MODE`` switch. This
module adds only what they lack, and wraps them where the behaviour overlaps:

* a **candle key** over (symbol, timeframe, bar close time) that depends on no release label
  such as ``APP_VERSION`` and on no strategy (R3.d);
* a **rule-aware setup key** (WP-C02; OPPORTUNITY_FUNNEL F4 ``setup_key``): venue, symbol,
  ``strategy_id``, strategy version, rule hash, timeframe, bar close time and direction. The rule
  hash is an input: the ``StrategyVersion`` identity hash (WP-A02; WP-IR-09, ``lineage`` excluded);
* **duplicate / conflict detection** over plain mappings: same key and same payload is
  ``F4.duplicate_setup``, same key and a different payload is ``F4.setup_conflict``;
* a **closed-bar freshness** check whose bound is a required argument (its value is OF-OD-12)
  and whose reasons are the canonical WP-IR-01 names ``F4.bar_not_closed`` / ``F4.bar_stale``;
* the SE-36 **no re-fire across a version boundary** rule (WP-C05;
  ``F4.bar_before_version_activation``);
* **fail-closed parsing** of the integrity settings; ``SIGNAL_INTEGRITY_MODE`` is delegated to
  A44's ``integrity_mode`` so its semantics stay identical.

Time convention. ``bar_close_ms`` is the venue close time, the last millisecond inside the bar
(Binance ``close_time`` = open + duration - 1), the value A44 stores as ``candle_close_ms``. Every
time is an integer UTC epoch millisecond (WP-IR-01 item 6): no local time, no DST, no host clock.

Integration boundary: no service imports this module and nothing here changes signal frequency.
Activating any part is a declared strategy-version boundary (R3 owner gates). SE-84 decides
whether the strategy version belongs in the key at all; the candle key serves either answer.
"""
from __future__ import annotations

import hashlib
import json
import numbers
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace
from typing import Iterable, Mapping

from shared.signal_identity import (DIRECTIONS, IDENTITY_VERSION as A44_IDENTITY_VERSION,
                                    TIMEFRAME_MS, IdentityError, SetupIdentity, integrity_mode)

CANDLE_KEY_VERSION = "wp2-ck-v1"
SETUP_KEY_VERSION = "wp2-sid-v2"
IDENTITY_VERSIONS = (A44_IDENTITY_VERSION, SETUP_KEY_VERSION)    # the first is today's default

# ── canonical RejectionRecord names (IMPLEMENTATION_WORKPLAN WP-IR-01; OPPORTUNITY_FUNNEL §8.2) ──
STAGE = "F4"
BAR_NOT_CLOSED = "F4.bar_not_closed"
BAR_STALE = "F4.bar_stale"
DATA_QUALITY = "F4.data_quality"
DUPLICATE_SETUP = "F4.duplicate_setup"
SETUP_CONFLICT = "F4.setup_conflict"
BAR_BEFORE_VERSION_ACTIVATION = "F4.bar_before_version_activation"
# Funnel rules carry a null sub_stage; shared identity producers carry ``shared.identity``.
SUB_STAGE = MappingProxyType({
    BAR_NOT_CLOSED: None, BAR_STALE: None, DATA_QUALITY: None,
    DUPLICATE_SETUP: "shared.identity", SETUP_CONFLICT: "shared.identity",
    BAR_BEFORE_VERSION_ACTIVATION: "shared.identity",
})
REASON_CODES = frozenset(SUB_STAGE)

# A44 freshness reasons (``signal_identity.freshness_at``, the reference rule) -> canonical codes.
A44_FRESHNESS_REASON = MappingProxyType({
    "decision_before_candle_close": BAR_NOT_CLOSED,
    "superseded_by_newer_candle": BAR_STALE,
    "timeframe_unknown": DATA_QUALITY,
})

MINUTE_MS = 60_000
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SYMBOL = re.compile(r"[A-Z0-9]{2,32}")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")                 # strategy_id, venue
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class IntegrityInputError(IdentityError):
    """An identity input is malformed; the candidate cannot be keyed and is ineligible."""


class IntegritySettingsError(RuntimeError):
    """An integrity setting is unknown or invalid; the service must refuse to start."""


def rejection_fields(reason_code: str) -> dict:
    """``stage`` / ``reason_code`` / ``sub_stage`` of a RejectionRecord for one of our codes."""
    if reason_code not in REASON_CODES:
        raise ValueError(f"unknown reason code {reason_code!r}")
    return {"stage": STAGE, "reason_code": reason_code, "sub_stage": SUB_STAGE[reason_code]}


# ── canonical primitives ────────────────────────────────────────────────────

def _sha(payload) -> str:
    try:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False)
    except (TypeError, ValueError) as exc:            # NaN/inf or a non-JSON value: no key
        raise IntegrityInputError(f"payload_not_canonical: {exc}") from None
    return hashlib.sha256(blob.encode()).hexdigest()


def _is_int(value) -> bool:
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def _strict_int(value, name) -> int:
    if value is None:
        raise IntegrityInputError(f"{name}_missing")
    if not _is_int(value):
        raise IntegrityInputError(f"{name}_malformed")
    return int(value)


def _match(pattern, value, name) -> str:
    if value is None:
        raise IntegrityInputError(f"{name}_missing")
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise IntegrityInputError(f"{name}_malformed")
    return value


def epoch_ms(moment: datetime) -> int:
    """Exact integer UTC epoch milliseconds of an aware datetime (no float rounding).

    A naive datetime is refused (its zone is unknown), as is a sub-millisecond value that the
    integer key could not represent without silent truncation."""
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        raise IntegrityInputError("datetime_not_timezone_aware")
    if moment.microsecond % 1000:
        raise IntegrityInputError("datetime_sub_millisecond")
    return (moment - _EPOCH) // timedelta(milliseconds=1)


def duration_of(timeframe: str) -> int:
    """Bar duration in ms for a supported timeframe (A44 ``TIMEFRAME_MS``); others are refused."""
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAME_MS:
        raise IntegrityInputError("timeframe_unknown")
    return TIMEFRAME_MS[timeframe]


# ── candle identity ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandleRef:
    """One closed exchange bar: (symbol, timeframe, bar close ms). No version, no strategy."""
    symbol: str
    timeframe: str
    bar_close_ms: int

    def __post_init__(self):
        _match(_SYMBOL, self.symbol, "symbol")
        step = duration_of(self.timeframe)
        close = _strict_int(self.bar_close_ms, "bar_close_time")
        if close <= 0:
            raise IntegrityInputError("bar_close_time_malformed")
        if (close + 1) % step:                 # epoch-aligned UTC bars only (same rule as A44)
            raise IntegrityInputError("bar_close_not_aligned")
        object.__setattr__(self, "bar_close_ms", close)      # numpy integers -> int

    @classmethod
    def from_open(cls, symbol: str, timeframe: str, bar_open_ms: int) -> "CandleRef":
        return cls(symbol, timeframe, _strict_int(bar_open_ms, "bar_open_time")
                   + duration_of(timeframe) - 1)

    @classmethod
    def from_setup_identity(cls, identity: SetupIdentity) -> "CandleRef":
        """The candle of an A44 identity (its version and policy fields are dropped)."""
        return cls(identity.symbol, identity.timeframe, identity.candle_close_ms)

    @property
    def bar_open_ms(self) -> int:
        return self.bar_close_ms - TIMEFRAME_MS[self.timeframe] + 1

    @property
    def bar_end_ms(self) -> int:
        """First millisecond after the bar."""
        return self.bar_close_ms + 1

    @property
    def key(self) -> str:
        return "ck_" + _sha([CANDLE_KEY_VERSION, self.symbol, self.timeframe,
                             self.bar_close_ms])[:40]


def candle_key(symbol: str, timeframe: str, bar_close_ms: int) -> str:
    return CandleRef(symbol, timeframe, bar_close_ms).key


# ── rule-aware setup key ────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuleIdentity:
    """What the key needs from a ``StrategyVersion``. ``rule_hash`` is computed elsewhere
    (WP-A02) over the identity fields with ``lineage`` excluded (WP-IR-09); here it is only
    validated. A release label such as ``APP_VERSION`` is neither a semantic version nor a
    hash, so it cannot stand in for either field (R3.d)."""
    strategy_id: str
    strategy_version: str          # MAJOR.MINOR.PATCH (SE-38)
    rule_hash: str                 # 64 lowercase hex characters (sha256)

    def __post_init__(self):
        _match(_NAME, self.strategy_id, "strategy_id")
        _match(_SEMVER, self.strategy_version, "strategy_version")
        _match(_HEX64, self.rule_hash, "rule_hash")


@dataclass(frozen=True)
class SetupKeyV2:
    """Idempotency identity of one strategy's setup on one closed bar. Bracket prices are not
    part of it; hash them with ``payload_hash`` and compare with ``classify_claim``."""
    venue: str
    candle: CandleRef
    rule: RuleIdentity
    direction: str

    def __post_init__(self):
        _match(_NAME, self.venue, "venue")
        if not isinstance(self.candle, CandleRef):
            raise IntegrityInputError("candle_malformed")
        if not isinstance(self.rule, RuleIdentity):
            raise IntegrityInputError("rule_identity_malformed")
        if self.direction not in DIRECTIONS:
            raise IntegrityInputError("direction_unsupported")

    @property
    def key(self) -> str:
        c, r = self.candle, self.rule
        return "sk2_" + _sha([SETUP_KEY_VERSION, self.venue, c.symbol, r.strategy_id,
                              r.strategy_version, r.rule_hash, c.timeframe, c.bar_close_ms,
                              self.direction])[:40]


def setup_key_v2(*, venue: str, symbol: str, strategy_id: str, strategy_version: str,
                 rule_hash: str, timeframe: str, bar_close_ms: int, direction: str) -> str:
    return SetupKeyV2(venue, CandleRef(symbol, timeframe, bar_close_ms),
                      RuleIdentity(strategy_id, strategy_version, rule_hash), direction).key


# ── duplicate and conflict detection ────────────────────────────────────────

NEW, DUPLICATE, CONFLICT = "new", "duplicate", "conflict"
_CLAIM_REASON = {NEW: None, DUPLICATE: DUPLICATE_SETUP, CONFLICT: SETUP_CONFLICT}


def payload_hash(payload) -> str:
    """Canonical hash of a JSON payload (e.g. the bracket); NaN and infinity are refused."""
    return _sha(payload)


@dataclass(frozen=True)
class KeyClaim:
    status: str                    # new | duplicate | conflict
    key: str
    payload_hash: str
    first_payload_hash: str | None = None

    @property
    def reason_code(self) -> str | None:
        return _CLAIM_REASON[self.status]


def _text(value, name) -> str:
    if not isinstance(value, str) or not value:
        raise IntegrityInputError(f"{name}_malformed")
    return value


def classify_claim(seen: Mapping[str, str], key: str, payload: str) -> KeyClaim:
    """Classify ``key`` against ``seen`` (key -> first payload hash). Reads only; never mutates."""
    _text(key, "key")
    _text(payload, "payload_hash")
    first = seen.get(key)
    if first is None:
        return KeyClaim(NEW, key, payload)
    return KeyClaim(DUPLICATE if first == payload else CONFLICT, key, payload, first)


def register_claim(seen: Mapping[str, str], key: str, payload: str) -> tuple:
    """Insert-once: return (claim, new mapping). The input mapping is never changed and the first
    payload of a key is never overwritten, whether the repeat is a duplicate or a conflict."""
    claim = classify_claim(seen, key, payload)
    after = dict(seen)
    if claim.status == NEW:
        after[key] = payload
    return claim, after


@dataclass(frozen=True)
class KeyConflict:
    key: str
    first_index: int | None        # None: the first payload came from the ``seen`` mapping
    index: int
    first_payload_hash: str
    payload_hash: str


@dataclass(frozen=True)
class DuplicateReport:
    claims: tuple                  # one KeyClaim per input entry, in input order

    @property
    def unique_keys(self) -> tuple:
        return tuple(c.key for c in self.claims if c.status == NEW)

    @property
    def duplicate_indices(self) -> tuple:
        return tuple(i for i, c in enumerate(self.claims) if c.status == DUPLICATE)

    @property
    def conflicts(self) -> tuple:
        first = {}
        for i, c in enumerate(self.claims):
            if c.status == NEW:
                first[c.key] = i
        return tuple(KeyConflict(c.key, first.get(c.key), i, c.first_payload_hash, c.payload_hash)
                     for i, c in enumerate(self.claims) if c.status == CONFLICT)

    @property
    def reason_counts(self) -> dict:
        counts = {}
        for c in self.claims:
            if c.reason_code:
                counts[c.reason_code] = counts.get(c.reason_code, 0) + 1
        return dict(sorted(counts.items()))


def detect_duplicates(entries: Iterable, *, seen: Mapping[str, str] | None = None) -> DuplicateReport:
    """Classify (key, payload_hash) entries in order; the first occurrence of a key wins."""
    state = dict(seen or {})                   # a private copy; the caller's mapping is untouched
    claims = []
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise IntegrityInputError("entry_malformed")
        claim = classify_claim(state, entry[0], entry[1])
        if claim.status == NEW:
            state[claim.key] = claim.payload_hash
        claims.append(claim)
    return DuplicateReport(tuple(claims))


# ── closed-bar freshness ────────────────────────────────────────────────────

@dataclass(frozen=True)
class BarFreshness:
    admissible: bool
    reason_code: str | None        # None | F4.bar_not_closed | F4.bar_stale | F4.data_quality
    age_ms: int | None             # now - first ms after the bar; None when the bar is malformed


def _positive_int_arg(value, name) -> int:
    if not _is_int(value) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer number of milliseconds")
    return int(value)


def closed_bar_freshness(*, bar_close_ms, timeframe_ms, now_ms, max_age_ms) -> BarFreshness:
    """A bar is usable from the millisecond after its close until ``max_age_ms`` later.

    * ``now_ms <= bar_close_ms`` (the bar is still forming, including its last millisecond):
      ``F4.bar_not_closed``;
    * age >= ``max_age_ms``: ``F4.bar_stale`` (the bound itself is already stale, as in A44);
    * a malformed or misaligned bar close: ``F4.data_quality``.

    ``max_age_ms`` has no default; its value per timeframe is owner decision OF-OD-12. It may not
    exceed one bar, the ceiling of the A44 reference rule: beyond it a newer bar has closed.
    Invalid arguments raise ``ValueError``; nothing here reads a clock."""
    step = _positive_int_arg(timeframe_ms, "timeframe_ms")
    bound = _positive_int_arg(max_age_ms, "max_age_ms")
    now = _positive_int_arg(now_ms, "now_ms")
    if bound > step:
        raise ValueError("max_age_ms may not exceed one bar (timeframe_ms)")
    if not _is_int(bar_close_ms) or int(bar_close_ms) <= 0 or (int(bar_close_ms) + 1) % step:
        return BarFreshness(False, DATA_QUALITY, None)
    age = now - (int(bar_close_ms) + 1)
    if age < 0:
        return BarFreshness(False, BAR_NOT_CLOSED, age)
    if age >= bound:
        return BarFreshness(False, BAR_STALE, age)
    return BarFreshness(True, None, age)


# ── version boundary (SE-36; WP-C05) ────────────────────────────────────────

def version_boundary_reason(*, bar_close_ms, activation_ms) -> str | None:
    """A version evaluates only bars whose close is at or after its activation minute, so a
    version change never re-keys and re-emits a bar the previous version already saw."""
    activation = _positive_int_arg(activation_ms, "activation_ms")
    if activation % MINUTE_MS:
        raise ValueError("activation_ms must be a whole UTC minute")
    if not _is_int(bar_close_ms) or int(bar_close_ms) <= 0:
        return DATA_QUALITY
    return BAR_BEFORE_VERSION_ACTIVATION if int(bar_close_ms) < activation else None


# ── fail-closed settings ────────────────────────────────────────────────────

SETTING_MODE = "SIGNAL_INTEGRITY_MODE"
SETTING_IDENTITY_VERSION = "SIGNAL_IDENTITY_VERSION"
SETTING_FRESHNESS_MAX_AGE = "SIGNAL_FRESHNESS_MAX_AGE_MS"
KNOWN_SETTINGS = (SETTING_MODE, SETTING_IDENTITY_VERSION, SETTING_FRESHNESS_MAX_AGE)
_SETTING_PREFIXES = ("SIGNAL_INTEGRITY_", "SIGNAL_IDENTITY_", "SIGNAL_FRESHNESS_")


@dataclass(frozen=True)
class IntegritySettings:
    mode: str                      # exactly what A44 ``integrity_mode`` returns
    identity_version: str          # a43-sid-v1 (today's key) | wp2-sid-v2
    freshness_max_age_ms: tuple    # sorted ((timeframe, ms), ...); empty: no bound declared

    def max_age_ms(self, timeframe: str) -> int:
        """The declared bound; an undeclared timeframe raises, it never falls back to a value."""
        for tf, ms in self.freshness_max_age_ms:
            if tf == timeframe:
                return ms
        raise IntegritySettingsError(f"no freshness bound declared for timeframe {timeframe!r}")


def _parse_max_age(raw: str) -> tuple:
    parts = [p.strip() for p in raw.split(",")]
    bounds = {}
    for part in parts:
        tf, sep, value = part.partition("=")
        tf, value = tf.strip(), value.strip()
        if not sep or not tf or not value:
            raise IntegritySettingsError(f"{SETTING_FRESHNESS_MAX_AGE}: malformed entry {part!r}")
        if tf not in TIMEFRAME_MS:
            raise IntegritySettingsError(f"{SETTING_FRESHNESS_MAX_AGE}: unknown timeframe {tf!r}")
        if tf in bounds:
            raise IntegritySettingsError(f"{SETTING_FRESHNESS_MAX_AGE}: timeframe {tf!r} repeated")
        if not (value.isascii() and value.isdigit()):
            raise IntegritySettingsError(f"{SETTING_FRESHNESS_MAX_AGE}: {tf} value {value!r} "
                                         "is not a whole number of milliseconds")
        ms = int(value)
        if not 0 < ms <= TIMEFRAME_MS[tf]:
            raise IntegritySettingsError(f"{SETTING_FRESHNESS_MAX_AGE}: {tf} bound {ms} "
                                         "must be in (0, one bar]")
        bounds[tf] = ms
    return tuple(sorted(bounds.items()))


def parse_integrity_settings(source: Mapping[str, str]) -> IntegritySettings:
    """Parse the integrity settings from an environment-like mapping; anything unknown or
    invalid raises (the service refuses to start).

    * ``SIGNAL_INTEGRITY_MODE`` is delegated to A44 ``integrity_mode``: absent means ``off``;
      an unknown value raises its ``RuntimeError`` unchanged;
    * ``SIGNAL_IDENTITY_VERSION``: absent means today's A44 key; otherwise one of
      ``IDENTITY_VERSIONS`` (trimmed, case-insensitive, like the mode);
    * ``SIGNAL_FRESHNESS_MAX_AGE_MS``: ``tf=ms`` entries separated by commas; absent means no
      bound is declared; there is no default value;
    * any other name with one of these prefixes is a typo and raises."""
    if not isinstance(source, Mapping):
        raise IntegritySettingsError("integrity settings must be a mapping of names to strings")
    for name in sorted(k for k in source if isinstance(k, str)):
        if name.startswith(_SETTING_PREFIXES) and name not in KNOWN_SETTINGS:
            raise IntegritySettingsError(f"unknown integrity setting {name!r}")
    for name in KNOWN_SETTINGS:
        if name in source and not isinstance(source[name], str):
            raise IntegritySettingsError(f"{name} must be a string")

    mode_cfg = SimpleNamespace(**({SETTING_MODE: source[SETTING_MODE]}
                                  if SETTING_MODE in source else {}))
    mode = integrity_mode(mode_cfg)

    if SETTING_IDENTITY_VERSION in source:
        version = source[SETTING_IDENTITY_VERSION].strip().lower()
        if version not in IDENTITY_VERSIONS:
            raise IntegritySettingsError(f"unknown {SETTING_IDENTITY_VERSION} {version!r}; "
                                         f"expected one of {IDENTITY_VERSIONS}")
    else:
        version = A44_IDENTITY_VERSION

    bounds = (_parse_max_age(source[SETTING_FRESHNESS_MAX_AGE])
              if SETTING_FRESHNESS_MAX_AGE in source else ())
    return IntegritySettings(mode, version, bounds)
