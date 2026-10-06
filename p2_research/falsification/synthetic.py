"""P2-F0 synthetic generators (validation of the battery itself; never real data).

A synthetic ROUND emulates what P2-D1 will hand to P2-F: the 48 planned P2-D0 cells evaluated on one panel of
39 symbols (tiers 2 / 6 / 31) over the frozen round-1 validation days 15..28.

Market model (per decision step; 24h cells on a 6-hourly grid, 4h cells on a 4-hourly grid, both on the real
``grid-15m-plus390s-v1`` offsets):
  factor  f_t = mu/G + ar * f_{t-1} + sigma_F/sqrt(G) * v_day * e_t        (BTC-like common factor)
  symbol  x_st = beta_s * f_t + sigma_s/sqrt(G) * v_day * e_st + planted drift
  e ~ Student t(4) scaled to unit variance; v_day = 1.0 (calm) / 1.8 (volatile), 2-state Markov by day.
Labels are path sums over the next H steps (overlapping, as in P2-C), so 24h positions entered on adjacent
decision rows share most of their label window.

Signals: one latent row score per cell, z = 0.85 * c_family + 0.53 * e_cell, c_family = a_family * g + ...,
where g is a row-level latent. The planted edge is a drift of ``delta * g`` spread over the label window of the row,
so a cell's edge is proportional to the correlation of its latent with g and grid neighbours share it (a plateau).

Costs (round trip, fractions): 20 bps fee, tier spread, BASE adds displayed-depth slippage and latency noise,
STRESS adds 2 x 10 bps (P2-X scenarios, ASSUMED values).
"""
from __future__ import annotations

import hashlib
import math
import random

from . import panel as PN

DAY0_MS = 1791158400000                      # 2026-10-05T00:00:00Z = P2-D0 eligible day 1 (synthetic dates)
OFFSET_MS = 390000                           # grid-15m-plus390s-v1
TIERS = (2, 6, 31)
FAMILY_SIZES = (("H01", 8), ("H02", 4), ("H03", 8), ("H04", 8), ("H05", 4), ("H06", 8), ("H07", 8))
CANDIDATE_PLAN = "P2D-R1-H01-004"           # H01-REF at 24h (lookback 4h, theta 1.0)


def _t4(rng):
    """Student t(4) scaled to unit variance."""
    z = rng.gauss(0.0, 1.0)
    c = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(4)) / 4.0
    return z / math.sqrt(c) / math.sqrt(2.0)


def trial_id(*parts) -> str:
    return "TR-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def symbols(rng):
    out = [("BTCUSDT", 0, 1.0, 0.004), ("ETHUSDT", 0, 1.1, 0.012)]
    for i in range(TIERS[1]):
        out.append((f"SYNA{i:02d}USDT", 1, rng.uniform(0.9, 1.4), 0.03))
    for i in range(TIERS[2]):
        out.append((f"SYNB{i:02d}USDT", 2, rng.uniform(0.8, 1.6), 0.045))
    return out


def simulate_panel(rng, *, G: int, H: int, horizon_ms: int, first_day: int, n_days: int, mu_day: float,
                   factor_sd_day: float, ar: float, syms, drift_fn=None, outlier=None):
    """Returns (rows, factor_by_day_prev) for the window days [first_day, first_day + n_days). ``drift_fn(row_key)``
    gives the planted label-window drift for a row (or 0). Row dicts carry only the market part; costs are added
    by ``costs``."""
    warm = 1
    tail = 2
    steps = (warm + n_days + tail) * G
    vol, v = [], 1.0
    for _ in range(warm + n_days + tail):
        if rng.random() < 0.15:
            v = 1.8 if v == 1.0 else 1.0
        vol.append(v)
    f, prev = [], 0.0
    for t in range(steps):
        e = mu_day / G + ar * prev + factor_sd_day / math.sqrt(G) * vol[t // G] * _t4(rng)
        f.append(e)
        prev = e
    inc = {}
    for s, tier, beta, isd in syms:
        inc[s] = [beta * f[t] + isd / math.sqrt(G) * vol[t // G] * _t4(rng) for t in range(steps)]
    step_ms = PN.DAY_MS // G
    rows, drift_add = [], {}
    # planted drift: spread over the H increments after the row
    if drift_fn is not None:
        for s, tier, beta, isd in syms:
            for t in range(warm * G, (warm + n_days) * G):
                d = drift_fn((s, t))
                if d:
                    for k in range(1, H + 1):
                        drift_add[(s, t + k)] = drift_add.get((s, t + k), 0.0) + d / H
    for s, tier, beta, isd in syms:
        x = inc[s]
        for t in range(warm * G, (warm + n_days) * G):
            day = first_day + t // G - warm
            t_ms = DAY0_MS + (day - 1) * PN.DAY_MS + (t % G) * step_ms + OFFSET_MS
            lab = sum(x[t + k] + drift_add.get((s, t + k), 0.0) for k in range(1, H + 1))
            if outlier and outlier[0] == day and outlier[1](s, t):
                lab += outlier[2]
            rows.append({"sym": s, "tier": tier, "t_ms": t_ms, "day": day, "_t": t, "_lab": lab,
                         "_next": x[t + 1], "_beta": beta, "_f": f[t]})
    # previous-day factor / symbol returns (PIT: known at the first decision of the day) for regime + benchmarks
    prev_day = {}
    for d in range(n_days):
        a, b = (warm + d - 1) * G, (warm + d) * G
        prev_day[first_day + d] = {"btc": sum(f[a:b]) * 1.0,
                                   "sym": {s: sum(inc[s][a:b]) for s, *_ in syms}}
    return rows, prev_day, step_ms


def costs(rows, rng, horizon_ms: int, refusal_p: float = 0.001):
    """Attach P2-X-like gross / net labels and the evidence row fields."""
    spread = {}
    for r in rows:
        if r["sym"] not in spread:
            spread[r["sym"]] = {0: 0.00001, 1: 0.0003, 2: rng.uniform(0.0002, 0.0008)}[r["tier"]]
    for r in rows:
        gross = r["_lab"]                       # arithmetic path sum: E[gross] = 0 under the null
        ide = gross - 0.002 - spread[r["sym"]]
        slip = 0.0 if r["tier"] == 0 else abs(rng.gauss(0.0, 0.00015))
        base = ide - slip + rng.gauss(0.0, 0.0003)
        refused = rng.random() < refusal_p
        r.update({"elig": 1, "sig": 0, "feat_avail_ms": r["t_ms"] - 1000, "entry_ms": r["t_ms"] + 1000,
                  "label_end_ms": r["t_ms"] + horizon_ms + 1000, "gross": gross, "net_idealized": ide,
                  "net_base": None if refused else base, "net_stress": None if refused else base - 0.002,
                  "depth_ok_500": not (r["tier"] == 2 and rng.random() < 0.003)})
    return rows


def day_context(rows, prev_day, syms, G):
    """Regime (from the previous UTC day's factor move, PIT) and the P2-D0 daily benchmarks BTC-TREND / TSMOM."""
    first = {}
    for r in rows:
        if r["t_ms"] % PN.DAY_MS == OFFSET_MS:
            first.setdefault(r["day"], {})[r["sym"]] = r
    out = {}
    sd = 0.025
    for d, pd in prev_day.items():
        fr = first.get(d, {})
        reg = "trending_up" if pd["btc"] > 0.5 * sd else ("trending_down" if pd["btc"] < -0.5 * sd else "neutral")
        btc = fr.get("BTCUSDT")
        trend = (btc["net_base"] or 0.0) if (btc and pd["btc"] > 0) else 0.0
        sel = [fr[s]["net_base"] for s in fr if pd["sym"].get(s, 0) > 0 and fr[s]["net_base"] is not None]
        ts = sum(sel) / len(sel) if sel else 0.0
        out[str(d)] = {"regime": reg, "bench": {"BENCH-CASH": 0.0, "BENCH-BTC-TREND": trend, "BENCH-TSMOM": ts}}
    return out


def strip(rows):
    keep = PN.ROW_FIELDS
    return [{k: r[k] for k in keep} for r in rows]


# ------------------------------------------------------------------ a full synthetic round (48 cells)
class Round:
    """One synthetic round: the 24h and 4h panels, the latent signals of all 48 planned cells and the evidence of
    any cell on demand."""

    def __init__(self, seed: int, plan: dict, *, mode: str = "null", n_days: int = 14, first_day: int = 15,
                 delta: float = 0.0, mu_day: float = 0.0, ar: float = 0.0, factor_sd_day: float = 0.025,
                 p_scale: float = 1.0, edge_family: str = "H01", kind: str = "in_sample", only=None):
        self.seed, self.mode, self.plan = seed, mode, plan
        self.first_day, self.n_days, self.kind = first_day, n_days, kind
        rng = random.Random(seed)
        self.syms = symbols(rng)
        self.beta = {s: b for s, _, b, _ in self.syms}
        self.cells = [t for t in plan["trials"] if only is None or t["plan_id"] in only]
        self.g = {}
        self.z = {}

        def latent(key):
            if key not in self.g:
                self.g[key] = rng.gauss(0.0, 1.0)
            return self.g[key]

        self.panels = {}
        need = {t["params"]["horizon"] for t in self.cells}
        for hz, G, H in (("24h", 4, 4), ("4h", 6, 1)):
            if hz not in need:
                continue
            hms = PN.HORIZON_MS[hz]
            dscale = 1.0 if hz == "24h" else 1.0 / 6.0
            pump = self.syms[10][0] if mode == "single_symbol" else None

            def drift(key, hz=hz, ds=dscale, pump=pump):
                d = delta * ds * latent((hz,) + key) if delta else 0.0
                if pump and key[0] == pump:
                    d += 0.05 * ds
                return d
            outlier = None
            if mode == "outlier_day":
                od = first_day + rng.randrange(max(1, n_days - 2))
                outlier = (od, lambda s, t, hz=hz: latent((hz, s, t)) > 1.0, 0.15)
            rows, prev, step = simulate_panel(rng, G=G, H=H, horizon_ms=hms, first_day=first_day, n_days=n_days,
                                              mu_day=mu_day, factor_sd_day=factor_sd_day, ar=ar, syms=self.syms,
                                              drift_fn=drift, outlier=outlier)
            for r in rows:
                latent((hz, r["sym"], r["_t"]))
            costs(rows, rng, hms)
            self.panels[hz] = {"rows": rows, "ctx": day_context(rows, prev, self.syms, G), "G": G}
        # latent cell signals: z = 0.85 c_fam + 0.53 e_cell ; c_fam = a g + sqrt(1-a^2) u_fam
        load = {f: (0.9 if edge_family in (f, "ALL") else 0.3) for f, _ in FAMILY_SIZES}
        self.flags = {}
        thr = {0.5: 1.0, 1.0: 1.3}
        for t in self.cells:
            hz = t["params"]["horizon"]
            rows = self.panels[hz]["rows"]
            fam = t["hypothesis"]
            a = load[fam]
            th = thr.get(t["params"].get("theta"), 1.15) / max(1e-9, p_scale)
            crng = random.Random(f"{seed}|{t['plan_id']}")
            urng = random.Random(f"{seed}|{fam}|u")
            fl = {}
            for r in rows:
                key = (hz, r["sym"], r["_t"])
                u = urng.gauss(0.0, 1.0)
                c = a * self.g[key] + math.sqrt(1 - a * a) * u
                z = 0.85 * c + 0.53 * crng.gauss(0.0, 1.0)
                fl[(r["sym"], r["t_ms"])] = self._mode_signal(r, z, th)
            self.flags[t["plan_id"]] = {k: 1 for k, v in fl.items() if v}

    def _mode_signal(self, r, z, th):
        m = self.mode
        if m in ("lookahead_meta", "lookahead_hidden"):
            return r["_next"] > 0.012 and z > th - 1.0
        if m == "beta":
            return self.beta[r["sym"]] > 1.3 and z > th - 0.8
        if m == "timing_beta":
            return r["_f"] > 0 and z > th - 0.8
        if m == "relative_trap":
            return z > th - 1.8
        if m == "small_n":
            return z > 3.2
        if m == "single_symbol":
            return z > th
        return z > th

    def evidence(self, plan_id: str, registration: dict, *, claimed: str | None = None) -> dict:
        t = next(c for c in self.cells if c["plan_id"] == plan_id)
        hz = t["params"]["horizon"]
        P = self.panels[hz]
        fl = self.flags[plan_id]
        rows = strip(P["rows"])
        for r in rows:
            r["sig"] = 1 if fl.get((r["sym"], r["t_ms"])) else 0
        days = list(range(self.first_day, self.first_day + self.n_days))
        if self.mode == "lookahead_meta":
            for r in rows:
                if r["sig"]:
                    r["feat_avail_ms"] = r["t_ms"] + 900000
        if self.mode == "clones":
            extra = [dict(r) for r in rows if r["sig"] and (r["net_base"] or 0) > 0][:40]
            rows = rows + extra
        win = {"kind": self.kind, "round": 1, "validation_days": days,
               "day_start_ms": {str(d): DAY0_MS + (d - 1) * PN.DAY_MS for d in days}}
        if self.mode == "peak_boundary":
            # the window end moved to the cumulative-P&L peak of the candidate (selection on outcome)
            win["validation_days"] = days[: max(3, int(len(days) * 0.7))]
            win["day_start_ms"] = {str(d): DAY0_MS + (d - 1) * PN.DAY_MS for d in win["validation_days"]}
            rows = [r for r in rows if r["day"] in win["validation_days"]]
        ev = {"record": "tsb.p2f.evidence", "record_version": 1,
              "candidate": {"trial_id": self.trial_id(plan_id), "plan_id": plan_id,
                            "plan_entry_sha256": t["plan_entry_sha256"], "hypothesis": t["hypothesis"],
                            "horizon": hz, "direction": "long",
                            "kind": "information" if t["params"].get("mode") == "information" else "directional"},
              "registration": registration, "window": win, "rows": rows, "day_context": P["ctx"]}
        if isinstance(registration, dict) and "dataset" in registration:
            ev["dataset"] = registration["dataset"]
        if claimed == "reentry":
            ev["claimed_positions"] = [[r["sym"], r["t_ms"]] for r in rows if r["sig"]]
        return ev

    def trial_id(self, plan_id):
        return trial_id("synthetic", self.seed, self.mode, plan_id)

    def all_trial_ids(self):
        return [self.trial_id(t["plan_id"]) for t in self.cells]
