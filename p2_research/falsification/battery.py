"""P2-F0 adversarial validation battery: integrity -> minimum n -> falsification tests -> verdict.

Input: an evidence bundle (``tsb.p2f.evidence`` v1, schema in ``contracts/f0_evidence_schema_v1.json``) holding the
candidate's full eligible decision-row panel for the evaluation window, plus an optional round context (sibling
p-values, every evaluated trial's day series, ledger counts, grid-neighbour results). Output: a ``tsb.p2f.verdict``
record listing every test with its status, numbers and reason, and exactly one verdict from the frozen taxonomy.

The battery recomputes everything from the rows. It reads no market data, no ledger file unless asked, never
writes anywhere, and never imports ``p2_forward``.
"""
from __future__ import annotations

import hashlib
import json
import math
import random

from . import panel as PN
from . import stats as S
from .. import instrument as IN
from .. import ledger as LG

RECORD, RECORD_VERSION = "tsb.p2f.verdict", 1
EVIDENCE_RECORD = "tsb.p2f.evidence"
PASS, FAIL, UNDET, NOT_RUN, NA = "PASS", "FAIL", "UNDETERMINABLE", "NOT_RUN", "NOT_APPLICABLE"
# effect of a FAIL / UNDETERMINABLE, from strongest to weakest
EFFECTS = ("invalid", "min_n", "reject", "fragile", "insufficient", "provisional", "none")
VERDICT_OF = {"invalid": "INVALID_EVIDENCE", "min_n": "INSUFFICIENT_EVIDENCE", "reject": "REJECTED",
              "fragile": "FRAGILE", "insufficient": "INSUFFICIENT_EVIDENCE",
              "provisional": "FORWARD_CONFIRMATION_REQUIRED", "none": "PROVISIONAL"}
HYP_RE = ("H01", "H02", "H03", "H04", "H05", "H06", "H07")


class EvidenceError(ValueError):
    pass


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _r(v):
    """Stable float formatting for the record (12 significant digits); inf/nan become strings."""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return str(v)
        return float(f"{v:.12g}")
    if isinstance(v, dict):
        return {k: _r(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_r(x) for x in v]
    return v


class Battery:
    def __init__(self, protocol: dict, contract_set_sha256: str, plan: dict | None = None,
                 reps_profile: dict | None = None):
        """``reps_profile`` (synthetic calibration only) lowers bootstrap / placebo repetitions; any verdict produced
        with it is marked ``profile = calibration`` and is not a P2-F0 verdict on a candidate."""
        self.P = protocol
        self.csha = contract_set_sha256
        self.plan = plan
        self.profile = "calibration" if reps_profile else "protocol"
        self.reps = {"bootstrap": protocol["inference"]["bootstrap_reps"],
                     "random_entry": protocol["placebo"]["random_entry_reps"],
                     "time_shift": protocol["placebo"]["time_shift_reps"]}
        if reps_profile:
            self.reps.update(reps_profile)
        self._plan_ix = {t["plan_id"]: t for t in (plan or {}).get("trials", [])}

    # ------------------------------------------------------------------ helpers
    def seed(self, trial_id: str, test_id: str) -> int:
        return int(hashlib.sha256(f"{self.csha}|{trial_id}|{test_id}".encode()).hexdigest()[:12], 16)

    def _blk(self, hz):
        return self.P["inference"]["mean_block_days"][hz], self.P["inference"]["hac_lag_days"][hz]

    @property
    def inference_version(self):
        return int(self.P["inference"].get("combine_version", 1))

    def _alpha(self, p, m, blk, lag, tid, name, L=None):
        """Net-alpha test under the inference version of the frozen protocol."""
        if self.inference_version >= 2:
            LL = L if L is not None else S.block_length(len(p), blk)
            return S.alpha_test_v2(p, m, LL, self.reps["bootstrap"], self.seed(tid, name))
        return S.alpha_test(p, m, L or blk, L or lag, self.reps["bootstrap"], self.seed(tid, name))

    def _core(self, x, blk, lag, tid, name):
        if self.inference_version >= 2:
            return S.core_test_v2(x, S.block_length(len(x), blk), self.reps["bootstrap"], self.seed(tid, name))
        return S.core_test(x, blk, lag, self.reps["bootstrap"], self.seed(tid, name))

    @staticmethod
    def _test(tests, tid, status, effect, **kw):
        tests[tid] = {"status": status, "effect_if_not_pass": effect, **kw}

    # ------------------------------------------------------------------ integrity (structure, binding, PIT)
    def _integrity(self, ev, T):
        P = self.P
        ok = True

        def fail(tid, reason, **kw):
            nonlocal ok
            ok = False
            self._test(T, tid, FAIL, "invalid", reason=reason, **kw)

        # I01 schema
        try:
            if ev.get("record") != EVIDENCE_RECORD or ev.get("record_version") != 1:
                raise EvidenceError("not a tsb.p2f.evidence v1 record")
            c, w, reg = ev["candidate"], ev["window"], ev["registration"]
            for k in ("trial_id", "plan_id", "plan_entry_sha256", "hypothesis", "horizon", "direction", "kind"):
                if not isinstance(c.get(k), str) or not c[k]:
                    raise EvidenceError(f"candidate.{k} missing")
            if c["direction"] != "long":
                raise EvidenceError("only long-only spot candidates exist (P2-D0)")
            if c["horizon"] not in PN.HORIZON_MS:
                raise EvidenceError("horizon must be 4h or 24h (P2-D0)")
            if c["hypothesis"] not in HYP_RE:
                raise EvidenceError("hypothesis must be one of H01..H07")
            if c["kind"] == "information":
                raise EvidenceError("an information-mode trial is not a strategy; P2-F0 evaluates executable claims only")
            if "risk_inputs" in ev:
                raise EvidenceError("risk_inputs refused: P2-RM0 is pending D-RM0-2 closure")
            if w.get("kind") not in ("in_sample", "forward") or not isinstance(w.get("round"), int):
                raise EvidenceError("window.kind in {in_sample, forward} and window.round required")
            if not isinstance(w.get("validation_days"), list) or not w["validation_days"]:
                raise EvidenceError("window.validation_days required")
            if not isinstance(w.get("day_start_ms"), dict):
                raise EvidenceError("window.day_start_ms required")
            rows = ev["rows"]
            if not isinstance(rows, list) or not rows:
                raise EvidenceError("rows required")
            for r in rows:
                if set(PN.ROW_FIELDS) - set(r):
                    raise EvidenceError(f"row fields missing: {sorted(set(PN.ROW_FIELDS) - set(r))}")
                if not isinstance(r["sym"], str) or not isinstance(r["t_ms"], int) or not isinstance(r["day"], int):
                    raise EvidenceError("row sym/t_ms/day types")
                for k in ("gross", "net_idealized", "net_base", "net_stress"):
                    if r[k] is not None and (not isinstance(r[k], (int, float)) or not math.isfinite(r[k])):
                        raise EvidenceError(f"row {k} must be a finite number or null")
            self._test(T, "I01_schema", PASS, "invalid")
        except (EvidenceError, KeyError, TypeError) as e:
            fail("I01_schema", str(e))
            return False
        hz_ms = PN.HORIZON_MS[c["horizon"]]
        # I02 binding to frozen contracts and the frozen P2-D0 plan
        dep = P["dependencies"]
        bad = []
        if reg.get("record") != "tsb.p2f.candidate_registration":
            bad.append("registration record")
        if reg.get("f0_contract_set_sha256") != self.csha:
            bad.append("f0_contract_set_sha256")
        if reg.get("p2d0_sums_sha256") != dep["p2d0"]["sha256"]:
            bad.append("p2d0_sums_sha256")
        if reg.get("p2x_v2_sums_sha256") != dep["p2x_v2"]["sha256"]:
            bad.append("p2x_v2_sums_sha256")
        if reg.get("trial_id") != c["trial_id"] or c["trial_id"] not in (reg.get("considered_trials") or []):
            bad.append("trial_id / considered_trials")
        if P["integrity"].get("dataset_binding"):
            ds = reg.get("dataset") or {}
            if not (isinstance(ds.get("dataset_id"), str) and isinstance(ds.get("dataset_hash"), str) and
                    len(ds["dataset_hash"]) == 64 and all(ch in "0123456789abcdef" for ch in ds["dataset_hash"])):
                bad.append("registration.dataset {dataset_id, dataset_hash} required")
            elif ev.get("dataset") != ds:
                bad.append("evidence.dataset differs from the registered dataset")
        pe = self._plan_ix.get(c["plan_id"])
        if self.plan is not None:
            if pe is None:
                bad.append("plan_id not in the frozen plan")
            else:
                if pe["plan_entry_sha256"] != c["plan_entry_sha256"]:
                    bad.append("plan_entry_sha256")
                if pe["hypothesis"] != c["hypothesis"] or pe["params"].get("horizon") != c["horizon"]:
                    bad.append("hypothesis / horizon differ from the plan entry")
                if pe["params"].get("mode") == "information":
                    bad.append("information-mode plan entry")
        if bad:
            fail("I02_binding", "binding mismatch", fields=bad)
        else:
            self._test(T, "I02_binding", PASS, "invalid")
        # I03 W3
        w3s = int(LG.W3_START.timestamp() * 1000)
        w3e = int(LG.W3_END.timestamp() * 1000) + 1          # W3 end is exclusive at microsecond .497803
        hit = [r for r in rows if (w3s <= r["t_ms"] < w3e) or (r["label_end_ms"] is not None and
                                                               r["t_ms"] < w3e and r["label_end_ms"] > w3s)]
        if hit:
            fail("I03_w3", "rows inside or reading the sealed holdout W3", n=len(hit))
        else:
            self._test(T, "I03_w3", PASS, "invalid")
        # I04 window = frozen P2-D0 layout; rows only inside declared days
        lay = P["integrity"]["round_layout"].get(str(w["round"]))
        vd = sorted(w["validation_days"])
        why = []
        if w["kind"] == "in_sample":
            if lay is None:
                why.append(f"round {w['round']} has no frozen layout in this F version")
            elif vd != list(range(lay["validation_days"][0], lay["validation_days"][1] + 1)):
                why.append("validation days differ from the frozen P2-D0 layout")
            elif any(d >= lay["forward_from_day"] for d in vd):
                why.append("in-sample window reads forward-untouched days")
        else:
            fr = reg.get("forward_registration") or {}
            if not fr or vd != list(range(fr.get("first_day", -1), fr.get("first_day", -1) + fr.get("n_days", 0))):
                why.append("forward window differs from its registration")
        dset = set(vd)
        try:
            dstart = {int(k): int(v) for k, v in w["day_start_ms"].items()}
        except (TypeError, ValueError):
            dstart = {}
            why.append("day_start_ms malformed")
        if set(dstart) != dset:
            why.append("day_start_ms keys differ from validation_days")
        out = [r for r in rows if r["day"] not in dset or not (dstart.get(r["day"], -1) <= r["t_ms"] <
                                                                dstart.get(r["day"], -1) + PN.DAY_MS)]
        if out:
            why.append(f"{len(out)} rows outside their declared day / window")
        if why:
            fail("I04_window", "; ".join(why))
        else:
            self._test(T, "I04_window", PASS, "invalid")
        # I05 PIT
        md = P["integrity"]["max_entry_delay_ms"]
        pit = [r for r in rows if r["feat_avail_ms"] is None or r["feat_avail_ms"] > r["t_ms"] or
               not (r["t_ms"] < r["entry_ms"] <= r["t_ms"] + md) or
               (r["label_end_ms"] is not None and r["label_end_ms"] < r["t_ms"] + hz_ms)]
        if pit:
            fail("I05_pit", "feature available after T, entry not strictly after T, or label shorter than horizon",
                 n=len(pit))
        else:
            self._test(T, "I05_pit", PASS, "invalid")
        # I06 uniqueness and grid
        keys = [(r["sym"], r["t_ms"]) for r in rows]
        g = P["integrity"]
        offgrid = [k for k in keys if (k[1] - g["grid_offset_ms"]) % g["grid_step_ms"]]
        if len(set(keys)) != len(keys) or offgrid:
            fail("I06_unique_grid", "duplicate (symbol, decision time) rows (clone replication) or off-grid times",
                 duplicates=len(keys) - len(set(keys)), off_grid=len(offgrid))
        else:
            self._test(T, "I06_unique_grid", PASS, "invalid")
        # I08 one quote currency (fail closed; the D-RM0-2 lesson)
        try:
            quotes = sorted({IN.binance_spot_instrument(s).quote_currency for s in {r["sym"] for r in rows}})
            qerr = None if len(quotes) == 1 else "mixed quote currencies: returns are not aggregated across numeraires"
        except ValueError as e:
            quotes, qerr = [], str(e)
        if qerr:
            fail("I08_quote_currency", qerr, quotes=quotes)
        else:
            self._test(T, "I08_quote_currency", PASS, "invalid", quote=quotes[0])
        # I09 signals only on eligible rows
        ne = sum(1 for r in rows if r["sig"] and not r["elig"])
        if ne:
            fail("I09_signal_eligible", "signal on a non-evaluable row", n=ne)
        else:
            self._test(T, "I09_signal_eligible", PASS, "invalid")
        return ok

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, ev: dict, context: dict | None = None) -> dict:
        ctx = context or {}
        P = self.P
        T = {}
        info = {}
        ok = self._integrity(ev, T)
        cand = ev.get("candidate", {}) if isinstance(ev, dict) else {}
        if not ok:
            return self._finish(ev, cand, T, info)
        hz = cand["horizon"]
        hz_ms = PN.HORIZON_MS[hz]
        tid = cand["trial_id"]
        blk, lag = self._blk(hz)
        w = ev["window"]
        kind = w["kind"]
        vdays = sorted(w["validation_days"])
        rows, rows_all = _purge(ev)
        info["latest_label_end_read_ms"] = max((r["label_end_ms"] or 0) for r in rows_all)
        info["purged_label_tail_rows"] = len(rows_all) - len(rows)
        info["purged_label_tail_signal_rows"] = sum(1 for r in rows_all if r["sig"]) - sum(1 for r in rows if r["sig"])
        rbs = PN.by_symbol(rows)
        flags = PN.signal_flags(rows)
        pos = PN.build_positions(rbs, flags, hz_ms)
        # I07 claimed positions must equal the rebuild
        if "claimed_positions" in ev:
            claimed = sorted((s, int(t)) for s, t in ev["claimed_positions"])
            rebuilt = sorted((p["sym"], p["t_ms"]) for p in pos)
            if claimed != rebuilt:
                self._test(T, "I07_positions_match", FAIL, "invalid",
                           reason="claimed positions differ from the P2-D0 rebuild (clones / re-entry while open)",
                           claimed=len(claimed), rebuilt=len(rebuilt))
                return self._finish(ev, cand, T, info)
            self._test(T, "I07_positions_match", PASS, "invalid")
        else:
            self._test(T, "I07_positions_match", NA, "none", reason="no claimed positions supplied")
        # ---- minimum n
        cl, _ = PN.cluster_series(pos, "net_base")
        x = [v for _, v in cl]
        fac = PN.day_factors(rows)
        adays = [d for d in vdays if d in fac]
        port_all = PN.portfolio_series(pos, "net_base", vdays)
        pmap = dict(zip(vdays, port_all))
        p_ser = [pmap[d] for d in adays]
        m_ser = [fac[d][1] for d in adays]
        mn = P["min_n"]
        a_tmp = S.alpha_series(p_ser, m_ser)[0] if len(adays) >= 3 else []
        n_eff = S.n_eff(a_tmp, lag) if len(a_tmp) >= 2 else float(len(a_tmp))
        counts = {"validation_days": len(vdays), "active_days": len(x), "positions": len(pos),
                  "symbols": len({p["sym"] for p in pos}), "n_eff_days": n_eff, "factor_days": len(adays)}
        info["counts"] = counts
        short = [k for k in ("validation_days", "active_days", "positions", "symbols", "n_eff_days")
                 if counts[k] < mn[k]]
        if short:
            self._test(T, "N01_min_n", FAIL, "min_n", reason="below the pre-registered minimum", short=short)
            return self._finish(ev, cand, T, info)
        self._test(T, "N01_min_n", PASS, "min_n")
        reps = self.reps["bootstrap"]
        al = self._alpha(p_ser, m_ser, blk, lag, tid, "alpha")
        a_ser = al.pop("series")
        info["alpha"] = al
        # ---- I10 implausibility tripwire (market-adjusted; before anything is reported)
        imp = P["implausibility"]
        sr_max = imp["max_plausible_annual_sharpe"] / math.sqrt(365.0)
        psr_hi = S.psr(a_ser, sr_max)
        xpos = PN.excess_positions(pos, PN.time_mean_gross(rows))
        xv = [p["net_base"] for p in xpos if p["net_base"] is not None]
        wl = _wilson_lo(sum(1 for v in xv if v > 0), len(xv))
        if psr_hi >= imp["psr_trigger"] or wl > imp["max_plausible_hit_rate"]:
            self._test(T, "I10_implausible", FAIL, "invalid", reason="too good to be plausible: leakage audit required",
                       psr_alpha_above_max_sharpe=psr_hi, excess_hit_rate_wilson_lo=wl)
            return self._finish(ev, cand, T, info)
        self._test(T, "I10_implausible", PASS, "invalid", psr_alpha_above_max_sharpe=psr_hi,
                   excess_hit_rate_wilson_lo=wl)
        if ctx.get("d0_category") == "REJECTED":
            self._test(T, "D0_category", FAIL, "reject", reason="P2-D0 classified the trial REJECTED")
        elif ctx.get("d0_category") is not None:
            self._test(T, "D0_category", PASS, "reject", category=ctx["d0_category"])
        # ---- economic core
        core = self._core(x, blk, lag, tid, "core")
        info["net_base_cluster"] = core
        E = P["economic"]
        a01 = al["alpha"] > P["attribution"]["alpha_point_must_exceed"]
        self._test(T, "A01_net_alpha_positive", PASS if a01 else FAIL, "reject", alpha=al["alpha"], beta=al["beta"],
                   reason=None if a01 else "net alpha <= 0: market exposure, not the signal, explains the return "
                                           "(or the signal does not pay its costs)")
        e01 = core["hi95"] >= 0
        self._test(T, "E01_net_base_not_negative", PASS if e01 else FAIL, "reject", mean=core["mean"],
                   hi95=core["hi95"], reason=None if e01 else "EXEC-BASE net significantly negative")
        e09 = core["mean"] > E["net_base_point_must_exceed"]
        self._test(T, "E09_net_base_positive_point", PASS if e09 else FAIL, "fragile", mean=core["mean"],
                   reason=None if e09 else "EXEC-BASE net not positive in this window")
        both = [p for p in pos if p["gross"] is not None and p["net_base"] is not None]
        g = [v for _, v in PN.cluster_series(both, "gross")[0]]
        cost = S.mean([p["gross"] - p["net_base"] for p in both]) if both else math.inf
        if len(g) >= 3:
            gt = self._core(g, blk, lag, tid, "gross")
            e02 = gt["hi95"] >= cost
            self._test(T, "E02_gross_covers_cost", PASS if e02 else FAIL, "reject", gross_mean=gt["mean"],
                       gross_hi95=gt["hi95"], mean_cost=cost,
                       reason=None if e02 else "even the upper bound of the gross edge cannot pay the costs")
        else:
            self._test(T, "E02_gross_covers_cost", UNDET, "insufficient", reason="too few gross clusters")
        # cost-to-gross on the market-adjusted gross edge (gross alpha) so the market drift cannot hide the costs
        gp = PN.portfolio_series(pos, "gross", vdays)
        gpm = dict(zip(vdays, gp))
        galpha = S.mean(S.alpha_series([gpm[d] for d in adays], m_ser)[0])
        ctg = (galpha - al["alpha"]) / galpha if galpha > 0 else math.inf
        e05 = ctg <= E["cost_to_gross_max"]
        self._test(T, "E05_cost_to_gross", PASS if e05 else FAIL, "fragile", cost_to_gross=ctg, gross_alpha=galpha,
                   reason=None if e05 else "costs consume more than the allowed share of the gross edge")
        sp = PN.portfolio_series(pos, "net_stress", vdays)
        spm = dict(zip(vdays, sp))
        s_alpha = S.mean(S.alpha_series([spm[d] for d in adays], m_ser)[0])
        sx = [v for _, v in PN.cluster_series(pos, "net_stress")[0]]
        e03 = s_alpha > E["net_stress_point_must_exceed"] and bool(sx) and S.mean(sx) > 0
        self._test(T, "E03_net_stress_positive", PASS if e03 else FAIL, "fragile", stress_alpha=s_alpha,
                   stress_mean=S.mean(sx) if sx else None,
                   reason=None if e03 else "not positive under EXEC-STRESS (alpha or net)")
        cpos = control_positions(rows, rbs, hz_ms)
        info["info_effect_gross"] = info_effect(pos, cpos)
        ccl = dict(PN.cluster_series(cpos, "net_base")[0])
        diffs = [v - ccl[d] for d, v in cl if d in ccl]
        if diffs:
            e04 = S.mean(diffs) > 0
            self._test(T, "E04_vs_control", PASS if e04 else FAIL, "fragile", mean_diff=S.mean(diffs),
                       reason=None if e04 else "no better than the P2-D0 control on the same days")
        else:
            self._test(T, "E04_vs_control", UNDET, "insufficient", reason="no common active day with the control")
        vals = [p["net_base"] for p in pos if p["net_base"] is not None]
        nref = len(pos) - len(vals)
        cref = sum(1 for p in cpos if p["net_base"] is None) / len(cpos) if cpos else 0.0
        rate = nref / len(pos)
        floor = min(vals) if vals else 0.0
        ipos = [dict(p, net_base=(p["net_base"] if p["net_base"] is not None else
                                  (p["net_stress"] if p["net_stress"] is not None else floor))) for p in pos]
        ip = PN.portfolio_series(ipos, "net_base", vdays)
        ipm = dict(zip(vdays, ip))
        i_alpha = S.mean(S.alpha_series([ipm[d] for d in adays], m_ser)[0])
        e06 = rate <= E["refusal_rate_max"] and abs(rate - cref) <= E["refusal_gap_signal_vs_control_max"] and \
            not (al["alpha"] > 0 and i_alpha <= 0)
        self._test(T, "E06_refusals", PASS if e06 else FAIL, "fragile", refusal_rate=rate, control_refusal_rate=cref,
                   imputed_alpha=i_alpha,
                   reason=None if e06 else "execution refusals are frequent, selective, or decide the sign")
        known = [p for p in pos if p["depth_ok_500"] is not None]
        if len(known) < len(pos) // 2:
            self._test(T, "E07_capacity_500", UNDET, "provisional", reason="depth support unknown for most positions")
        else:
            sub = [p for p in known if p["depth_ok_500"]]
            sps = PN.portfolio_series(sub, "net_base", vdays)
            spd = dict(zip(vdays, sps))
            c_alpha = S.mean(S.alpha_series([spd[d] for d in adays], m_ser)[0]) if sub else -math.inf
            e07 = c_alpha > 0
            self._test(T, "E07_capacity_500", PASS if e07 else FAIL, "fragile",
                       supported_share=len(sub) / len(known), supported_alpha=c_alpha,
                       reason=None if e07 else "no edge where 500 USDT fits the displayed depth (capacity)")
        self._attribution(T, ev, p_ser, m_ser, adays, fac, lag, al)
        # ---- robustness
        self._robustness(T, ev, pos, cl, x, a_ser, adays, al, p_ser, m_ser, vdays, lag, blk, rbs, flags, hz_ms,
                         tid, ctx, info["info_effect_gross"])
        # ---- placebos (same alpha statistic, same position rule)
        self._placebos(T, rows, rbs, flags, pos, al["alpha"], hz_ms, tid, vdays, adays, m_ser)
        # ---- significance and multiplicity
        self._multiplicity(T, cand, al, a_ser, adays, vdays, blk, lag, tid, ctx, kind,
                           ev["registration"].get("forward_registration"))
        return self._finish(ev, cand, T, info)

    # ------------------------------------------------------------------ parts
    def _attribution(self, T, ev, p_ser, m_ser, adays, fac, lag, al):
        A = self.P["attribution"]
        raw = S.mean(p_ser)
        res, undet = {}, []
        dc = ev.get("day_context") or {}
        for model in A["gate_models"] + A["reported_models"] + [["mkt", b] for b in self.P["economic"]["benchmarks_compared"]]:
            name = "+".join(model)
            cols, ok = [], True
            for f in model:
                if f == "mkt":
                    cols.append(m_ser)
                elif f == "btc":
                    v = [fac[d][0] for d in adays]
                    ok = ok and all(x is not None for x in v)
                    cols.append(v)
                else:
                    v = [((dc.get(str(d)) or {}).get("bench") or {}).get(f) for d in adays]
                    ok = ok and all(x is not None for x in v)
                    cols.append(v)
            if not ok or len(p_ser) < len(model) + 3:
                undet.append(name)
                continue
            try:
                res[name] = S.ols_alpha(p_ser, cols, lag)
            except S.StatsError:
                undet.append(name)
        det = {k: {"alpha": r["alpha"], "betas": r["betas"], "t_alpha": r["t_alpha"], "r2": r["r2"]}
               for k, r in res.items()}
        btc = res.get("btc")
        if btc is None:
            self._test(T, "A02_btc_alpha_positive", UNDET, "provisional", reason="BTC factor not estimable")
        else:
            a2 = btc["alpha"] > 0
            self._test(T, "A02_btc_alpha_positive", PASS if a2 else FAIL, "fragile", alpha=btc["alpha"],
                       reason=None if a2 else "BTC exposure explains the return")
        share = al["alpha"] / raw if raw > 0 else None
        if share is None:
            self._test(T, "A03_alpha_share", FAIL, "provisional", reason="raw portfolio mean not positive")
        else:
            a3 = share >= A["alpha_share_of_raw_min"]
            self._test(T, "A03_alpha_share", PASS if a3 else FAIL, "provisional", alpha_share=share, models=det,
                       reason=None if a3 else "most of the raw return is factor exposure")
        bm = ["mkt+" + b for b in self.P["economic"]["benchmarks_compared"]]
        got = [res[k]["alpha"] for k in bm if k in res]
        if len(got) < len(bm):
            self._test(T, "E08_benchmark_alpha", UNDET, "provisional", reason="benchmark day series incomplete",
                       undeterminable=undet)
        else:
            e8 = min(got) > 0
            self._test(T, "E08_benchmark_alpha", PASS if e8 else FAIL, "fragile",
                       alpha_vs={k: res[k]["alpha"] for k in bm},
                       reason=None if e8 else "explained by a trivial P2-D0 benchmark (BTC-TREND / TSMOM)")

    def _robustness(self, T, ev, pos, cl, x, a_ser, adays, al, p_ser, m_ser, vdays, lag, blk, rbs, flags, hz_ms,
                    tid, ctx, ieff):
        R = self.P["robustness"]
        lay = self.P["integrity"]["round_layout"].get(str(ev["window"]["round"]))
        kind = ev["window"]["kind"]
        dc = ev.get("day_context") or {}
        amap = dict(zip(adays, a_ser))
        folds = {}
        if kind == "in_sample" and lay:
            for f, (a, b) in sorted(lay["folds"].items()):
                folds[f] = [d for d in adays if a <= d <= b]
        regimes = {}
        for d in adays:
            g = (dc.get(str(d)) or {}).get("regime")
            if g is not None:
                regimes.setdefault(g, []).append(d)
        qual = {g: ds for g, ds in regimes.items() if len(ds) >= R["regime_min_days"]}
        reg_ok = len(qual) >= R["regime_min_regimes"]
        # ---- deterministic P2-D0-style conditions (block PROVISIONAL only)
        if folds:
            fm = {f: (S.mean([amap[d] for d in ds]) if ds else None) for f, ds in folds.items()}
            r1 = all(v is not None and v > 0 for v in fm.values())
            self._test(T, "R01_folds", PASS if r1 else FAIL, "provisional", fold_alpha=fm,
                       reason=None if r1 else "not positive in every validation fold")
        else:
            self._test(T, "R01_folds", NA, "none", reason="forward window: single block")
        k = max(1, math.ceil(R["remove_best_days_fraction"] * len(a_ser)))
        rest = sorted(a_ser)[:-k]
        r2 = bool(rest) and S.mean(rest) > 0
        self._test(T, "R02_remove_best_days", PASS if r2 else FAIL, "provisional", removed=k,
                   alpha_after=S.mean(rest) if rest else None, reason=None if r2 else "depends on its best days")
        beta = al["beta"]
        mday = dict(zip(adays, m_ser))
        res_pos = [dict(p, net_base=p["net_base"] - beta * mday[p["day"]]) for p in pos
                   if p["net_base"] is not None and p["day"] in mday]
        sym_stats = _symbol_stats(res_pos)
        r3 = sym_stats["loso_min"] > 0
        self._test(T, "R03_loso", PASS if r3 else FAIL, "provisional", min_alpha=sym_stats["loso_min"],
                   worst_symbol=sym_stats["loso_worst"], reason=None if r3 else "one symbol carries the result")
        kp = max(1, math.ceil(R["remove_top_positions_fraction"] * len(res_pos)))
        keep = sorted(res_pos, key=lambda p: p["net_base"])[:-kp]
        v4 = [y for _, y in PN.cluster_series(keep, "net_base")[0]]
        r4 = bool(v4) and S.mean(v4) > 0
        self._test(T, "R04_remove_top_positions", PASS if r4 else FAIL, "provisional", removed=kp,
                   alpha_after=S.mean(v4) if v4 else None, reason=None if r4 else "extreme trades carry the result")
        dsum = math.fsum(a_ser)
        day_share = max(a_ser) / dsum if dsum > 0 else math.inf
        r5 = sym_stats["top_share"] <= R["top_symbol_share_max"] and day_share <= R["best_day_share_max"]
        self._test(T, "R05_concentration", PASS if r5 else FAIL, "provisional", top_symbol_share=sym_stats["top_share"],
                   best_day_share=day_share, reason=None if r5 else "P&L concentrated in one symbol or day")
        r6 = sym_stats["tier_major_mean"] is not None and sym_stats["tier_major_mean"] > 0
        self._test(T, "R06_tier_majority", PASS if r6 else FAIL, "provisional", tier=sym_stats["tier_major"],
                   alpha=sym_stats["tier_major_mean"], reason=None if r6 else "not positive in the main tier")
        if not reg_ok:
            self._test(T, "R07_regimes", UNDET, "provisional", reason="sample covers fewer than two regimes",
                       days_by_regime={g: len(v) for g, v in regimes.items()})
        else:
            qm = {g: S.mean([amap[d] for d in ds]) for g, ds in qual.items()}
            r7 = all(v > 0 for v in qm.values())
            self._test(T, "R07_regimes", PASS if r7 else FAIL, "provisional", regime_alpha=qm,
                       reason=None if r7 else "negative in a regime: regime-dependent")
        # R08 plateau (gross information effect over the frozen grid neighbours)
        nb_ids = neighbours(self.plan, ev["candidate"]["plan_id"]) if self.plan else None
        nres = ctx.get("neighbour_info_effects") or {}
        if kind == "forward":
            self._test(T, "R08_plateau", NA, "none", reason="checked in-sample; a forward test confirms one frozen cell")
        elif not nb_ids or ieff is None or ieff <= 0 or any(nres.get(n) is None for n in nb_ids):
            self._test(T, "R08_plateau", UNDET, "provisional", neighbours=nb_ids, candidate_info_effect=ieff,
                       missing=[n for n in (nb_ids or []) if nres.get(n) is None],
                       reason="no neighbour result, or no positive gross information effect of the candidate")
        else:
            nm = [nres[n] for n in nb_ids]
            srt = sorted(nm)
            med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
            r8 = all(v > 0 for v in nm) and med >= R["plateau_min_ratio"] * ieff
            self._test(T, "R08_plateau", PASS if r8 else FAIL, "provisional",
                       neighbour_info_effects=dict(zip(nb_ids, nm)), candidate_info_effect=ieff,
                       reason=None if r8 else "knife-edge: grid neighbours do not share the gross information effect")
        # R09 one-row stale signal (leak / latency knife-edge), on net alpha
        lpos = PN.build_positions(rbs, PN.lag_flags(rbs, flags, R["lag_rows"]), hz_ms)
        if len(lpos) < self.P["min_n"]["positions"] or al["alpha"] <= 0:
            self._test(T, "R09_lag_retention", UNDET, "provisional", reason="too few lagged positions or alpha <= 0")
        else:
            lp = dict(zip(vdays, PN.portfolio_series(lpos, "net_base", vdays)))
            la = S.mean(S.alpha_series([lp[d] for d in adays], m_ser)[0])
            ret = la / al["alpha"]
            r9 = ret >= R["lag_retention_min"]
            self._test(T, "R09_lag_retention", PASS if r9 else FAIL, "fragile", retention=ret,
                       reason=None if r9 else "edge vanishes when the signal is one decision row stale "
                                              "(leakage or latency knife-edge)")
        # R10 dependence-assumption sensitivity (blocks PROVISIONAL only)
        ps = {}
        for L in self.P["inference"]["block_sensitivity_mean_block_days"]:
            ps[str(L)] = self._alpha(p_ser, m_ser, blk, lag, tid, f"block{L}", L=L)["p"]
        r10 = max(ps.values()) <= self.P["inference"]["block_sensitivity_max_p"]
        self._test(T, "R10_block_sensitivity", PASS if r10 else FAIL, "provisional", p_by_mean_block=ps,
                   reason=None if r10 else "significance depends on the dependence assumption")
        # ---- noise-calibrated joint fragility tests (FRAGILE effect)
        F = self.P["fragility"]
        if al["alpha"] <= 0:
            self._test(T, "R11_day_fragility", NOT_RUN, "none", reason="alpha <= 0 (rejected elsewhere)")
            self._test(T, "R12_symbol_fragility", NOT_RUN, "none", reason="alpha <= 0 (rejected elsewhere)")
            return
        self._day_fragility(T, a_ser, adays, folds, qual if reg_ok else {}, tid, F)
        self._symbol_fragility(T, res_pos, sym_stats, tid, F)

    def _day_fragility(self, T, a_ser, adays, folds, qual, tid, F):
        n = len(a_ser)
        mu = S.mean(a_ser)
        med = S.quantile(a_ser, 0.5)
        mad = S.quantile([abs(v - med) for v in a_ser], 0.5)
        t4_mad = 0.7406971                                    # median |T| of a standard t(4)
        k = max(1, math.ceil(self.P["robustness"]["remove_best_days_fraction"] * n))
        ix = {d: i for i, d in enumerate(adays)}

        def stats(v):
            srt = sorted(v)
            q1 = S.mean(srt[:-k])
            tot = math.fsum(v)
            q2 = max(v) / tot if tot > 0 else 1e9
            q3 = min(S.mean([v[ix[d]] for d in ds]) for ds in folds.values() if ds) if folds and all(
                folds.values()) else None
            q4 = min(S.mean([v[ix[d]] for d in ds]) for ds in qual.values()) if qual else None
            return [q1, q2, q3, q4]

        obs = stats(a_ser)
        rng = random.Random(self.seed(tid, "day_fragility"))
        scale = mad / t4_mad if mad > 0 else S.sd(a_ser) / math.sqrt(2.0)   # robust: an outlier cannot widen its own reference
        ref = []
        for _ in range(F["reference_reps"]):
            v = [mu + scale * _t4(rng) for _ in range(n)]
            ref.append(stats(v))
        pj, per = S.joint_tail_p(obs, ref, [-1, +1, -1, -1])
        names = ["mean_after_best_days", "best_day_share", "min_fold_alpha", "min_regime_alpha"]
        ok = pj is None or pj > F["alpha_joint"]
        self._test(T, "R11_day_fragility", PASS if ok else FAIL, "fragile", p_joint=pj,
                   p_by_stat={names[j]: v for j, v in per.items()}, observed=dict(zip(names, obs)),
                   reference="iid Student t(4) days, location = observed mean, scale = MAD / 0.7407 (robust)",
                   reason=None if ok else "more concentrated in days / folds / regimes than an honest edge of this "
                                          "size and noise would be")

    def _symbol_fragility(self, T, res_pos, obs_stats, tid, F):
        byday = {}
        for p in res_pos:
            byday.setdefault(p["day"], []).append(p)
        rng = random.Random(self.seed(tid, "symbol_fragility"))
        ref = []
        for _ in range(F["permutation_reps"]):
            perm = []
            for d in sorted(byday):
                ps = byday[d]
                vals = [p["net_base"] for p in ps]
                rng.shuffle(vals)
                perm.extend(dict(p, net_base=v) for p, v in zip(ps, vals))
            s = _symbol_stats(perm)
            ref.append([s["loso_min"], s["top_share"], s["tier_major_mean"]])
        obs = [obs_stats["loso_min"], obs_stats["top_share"], obs_stats["tier_major_mean"]]
        pj, per = S.joint_tail_p(obs, ref, [-1, +1, -1])
        names = ["loso_min_alpha", "top_symbol_share", "main_tier_alpha"]
        ok = pj is None or pj > F["alpha_joint"]
        self._test(T, "R12_symbol_fragility", PASS if ok else FAIL, "fragile", p_joint=pj,
                   p_by_stat={names[j]: v for j, v in per.items()}, observed=dict(zip(names, obs)),
                   reference="within-day permutation of position alpha across symbols",
                   reason=None if ok else "carried by one symbol / tier beyond what a within-day shuffle produces")

    def _placebos(self, T, rows, rbs, flags, pos, calpha, hz_ms, tid, vdays, adays, m_ser):
        Pp = self.P["placebo"]

        def alpha_of(pp):
            if not pp:
                return None
            ps = dict(zip(vdays, PN.portfolio_series(pp, "net_base", vdays)))
            return S.mean(S.alpha_series([ps[d] for d in adays], m_ser)[0])

        elig_by_tier = {}
        for r in rows:
            if r["elig"]:
                elig_by_tier.setdefault(r["tier"], []).append(r)
        for v in elig_by_tier.values():
            v.sort(key=lambda r: (r["t_ms"], r["sym"]))
        cnt = {}
        for p in pos:
            cnt[p["tier"]] = cnt.get(p["tier"], 0) + 1
        rng = random.Random(self.seed(tid, "random_entry"))
        K = self.reps["random_entry"]
        ge = 0
        for _ in range(K):
            v = alpha_of(PN.build_positions(rbs, PN.random_entry_flags(elig_by_tier, cnt, rng), hz_ms))
            if v is None or v >= calpha:
                ge += 1
        p_re = (1 + ge) / (1 + K)
        self._test(T, "P01_random_entry_not_worse", PASS if p_re <= Pp["random_entry_reject_above"] else FAIL,
                   "reject", p=p_re, reason=None if p_re <= Pp["random_entry_reject_above"] else
                   "worse than the median exposure-matched random entry")
        self._test(T, "P02_random_entry_beaten", PASS if p_re <= Pp["random_entry_beat_alpha"] else FAIL,
                   "provisional", p=p_re, reason=None if p_re <= Pp["random_entry_beat_alpha"] else
                   "not distinguishable from exposure-matched random entry")
        ts, tix = PN.time_index(rows)
        step = min(b - a for a, b in zip(ts, ts[1:])) if len(ts) > 1 else PN.DAY_MS
        hz_days = hz_ms / PN.DAY_MS
        min_off_ms = Pp["time_shift_min_offset_horizons"] * hz_ms
        kmin = math.ceil(min_off_ms / step)
        res = 1.0 / max(1e-9, len(vdays) - 2 * Pp["time_shift_min_offset_horizons"] * hz_days)
        if res > Pp["time_shift_alpha"] or len(ts) - 2 * kmin < 1:
            self._test(T, "P03_time_shift", UNDET, "provisional", resolution=res,
                       reason="too few distinguishable shifts in this window")
            return
        elig_keys = {(r["sym"], r["t_ms"]) for r in rows if r["elig"]}
        rng = random.Random(self.seed(tid, "time_shift"))
        Ks = self.reps["time_shift"]
        ge = 0
        for _ in range(Ks):
            kk = rng.randint(kmin, len(ts) - kmin)
            v = alpha_of(PN.build_positions(rbs, PN.shifted_flags(flags, ts, tix, kk, elig_keys), hz_ms))
            if v is None or v >= calpha:
                ge += 1
        p_ts = (1 + ge) / (1 + Ks)
        self._test(T, "P03_time_shift", PASS if p_ts <= Pp["time_shift_alpha"] else FAIL, "provisional", p=p_ts,
                   resolution=res, reason=None if p_ts <= Pp["time_shift_alpha"] else
                   "time-shifted copies of the signal do as well (alignment is not what pays)")

    def _multiplicity(self, T, cand, al, a_ser, adays, vdays, blk, lag, tid, ctx, kind="in_sample", freg=None):
        M = self.P["multiplicity"]
        a = self.P["inference"]["alpha_local"]
        scr = self.P["inference"]["screen_alpha"]
        s0 = al["p"] <= scr
        self._test(T, "S00_screen", PASS if s0 else FAIL, "insufficient", p=al["p"], p_boot=al["p_boot"],
                   p_hac_t=al.get("p_hac_t"), p_batch=al.get("p_batch"), p_fixedb=al.get("p_fixedb"),
                   block=al.get("block"), screen_alpha=scr,
                   reason=None if s0 else "net alpha not even suggestive (screen level)")
        if kind == "forward":
            setsz = int((freg or {}).get("set_size", 1))
            fam = dict(ctx.get("family_p") or {})
            fam[tid] = al["p"]
            if len(fam) >= setsz and setsz > 1:
                p_loc, how = S.holm(fam)[tid], "holm_forward_set"
            else:
                p_loc, how = min(1.0, al["p"] * setsz), "bonferroni_forward_set"
            s1 = p_loc <= a
            self._test(T, "S01_local_significance", PASS if s1 else FAIL, "insufficient", p_raw=al["p"],
                       p_local=p_loc, method=how, family_size=setsz,
                       reason=None if s1 else "forward net alpha not significant")
            self._test(T, "M01_romano_wolf", NA, "none", reason="forward: the set is pre-registered, no search")
            self._test(T, "S02_selection_screen", NA, "none", reason="forward: the set is pre-registered, no search")
            self._test(T, "M02_deflated_sharpe", NA, "none", reason="forward: the set is pre-registered, no search")
            return
        fam = dict(ctx.get("family_p") or {})
        fam[cand["plan_id"]] = al["p"]
        planned = [t["plan_id"] for t in (self.plan or {}).get("trials", []) if t["hypothesis"] == cand["hypothesis"]]
        m_fam = max(len(planned), int((ctx.get("ledger_hypothesis_trials") or {}).get(cand["hypothesis"], 0)), 1)
        if planned and all(fam.get(p) is not None for p in planned):
            p_loc, how = S.holm({p: fam[p] for p in planned})[cand["plan_id"]], "holm"
        else:
            p_loc, how = min(1.0, al["p"] * m_fam), "bonferroni"
        s1 = p_loc <= a
        self._test(T, "S01_local_significance", PASS if s1 else FAIL, "provisional", p_raw=al["p"], p_local=p_loc,
                   method=how, family_size=m_fam,
                   reason=None if s1 else "net alpha not significant after within-hypothesis correction")
        amap = dict(zip(adays, a_ser))
        aligned = [amap.get(d, 0.0) for d in vdays]
        rs = dict(ctx.get("round_series") or {})
        if len(rs) < 2:
            self._test(T, "M01_romano_wolf", UNDET, "provisional", reason="round series of the other trials absent")
            self._test(T, "S02_selection_screen", UNDET, "insufficient",
                       reason="the round (every evaluated trial) is required to count selection")
        else:
            rs[tid] = aligned
            if any(len(v) != len(aligned) for v in rs.values()):
                self._test(T, "M01_romano_wolf", UNDET, "provisional", reason="round series not aligned")
                self._test(T, "S02_selection_screen", UNDET, "insufficient", reason="round series not aligned")
            else:
                adj = S.romano_wolf(rs, blk, lag, self.reps["bootstrap"], self.seed(tid, "romano_wolf"))
                m1 = adj[tid] <= M["global_alpha"]
                self._test(T, "M01_romano_wolf", PASS if m1 else FAIL, "provisional", p_adj=adj[tid], trials=len(rs),
                           reason=None if m1 else "not significant after control over every evaluated trial")
                s2 = adj[tid] <= M["screen_rw_alpha"]
                self._test(T, "S02_selection_screen", PASS if s2 else FAIL, "insufficient", p_adj=adj[tid],
                           screen_rw_alpha=M["screen_rw_alpha"],
                           reason=None if s2 else "not even suggestive once selection across the round is counted")
        ntot = (ctx.get("ledger_counts") or {}).get("total_trials")
        if not ntot:
            self._test(T, "M02_deflated_sharpe", UNDET, "provisional", reason="ledger trial count absent")
            return
        rho = 0.0
        if len(rs) >= 2:
            names = sorted(rs)
            cs = [abs(_corr(rs[i], rs[j])) for kk, i in enumerate(names) for j in names[kk + 1:]]
            rho = S.mean(cs) if cs else 0.0
        neff = S.effective_trials(int(ntot), rho)
        d = S.deflated_sharpe(a_ser, neff)
        m2 = d["dsr"] >= M["dsr_min"]
        self._test(T, "M02_deflated_sharpe", PASS if m2 else FAIL, "provisional", n_trials=int(ntot),
                   mean_abs_rho=rho, **d,
                   reason=None if m2 else "Sharpe does not clear the expected maximum of the trials run")

    # ------------------------------------------------------------------ verdict
    def _finish(self, ev, cand, T, info):
        worst = "none"
        reasons = []
        for tid in sorted(T):
            t = T[tid]
            if t["status"] in (FAIL, UNDET):
                eff = t["effect_if_not_pass"]
                if EFFECTS.index(eff) < EFFECTS.index(worst):
                    worst = eff
                reasons.append(f"{tid}:{t['status']}")
        verdict = VERDICT_OF[worst]
        rec = {"record": RECORD, "record_version": RECORD_VERSION, "profile": self.profile,
               "protocol_id": self.P["protocol_id"], "protocol_version": self.P["version"],
               "f0_contract_set_sha256": self.csha,
               "thresholds_status": self.P["activation"]["thresholds_status"],
               "candidate": {k: cand.get(k) for k in ("trial_id", "plan_id", "hypothesis", "horizon")},
               "window": {k: (ev.get("window") or {}).get(k) for k in ("kind", "round")} if isinstance(ev, dict) else {},
               "verdict": verdict, "binding_effect": worst, "reasons": reasons, "tests": _r(T), "info": _r(info)}
        rec["verdict_id"] = hashlib.sha256(canon(rec).encode()).hexdigest()
        return rec


def _t4(rng):
    """Student t(4) draw (variance 2)."""
    z = rng.gauss(0.0, 1.0)
    c = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(4)) / 4.0
    return z / math.sqrt(c)


def _purge(ev):
    """Label-tail purge: rows whose label window ends after the last evaluation day are excluded (and counted)."""
    dstart = {int(k): int(v) for k, v in ev["window"]["day_start_ms"].items()}
    end = max(dstart.values()) + PN.DAY_MS
    rows_all = ev["rows"]
    return [r for r in rows_all if r["label_end_ms"] is None or r["label_end_ms"] <= end], rows_all


def _symbol_stats(res_pos):
    """LOSO minimum (day-cluster mean without one symbol), top-symbol share of the total, main-tier cluster mean."""
    Sd, Nd, Sds, Nds, bys, tiers = {}, {}, {}, {}, {}, {}
    for p in res_pos:
        d, s, v = p["day"], p["sym"], p["net_base"]
        Sd[d] = Sd.get(d, 0.0) + v
        Nd[d] = Nd.get(d, 0) + 1
        Sds[(d, s)] = Sds.get((d, s), 0.0) + v
        Nds[(d, s)] = Nds.get((d, s), 0) + 1
        bys[s] = bys.get(s, 0.0) + v
        tiers.setdefault(p["tier"], []).append(p)
    syms = sorted(bys)
    worst, wsym = math.inf, None
    for s in syms:
        vals = []
        for d in Sd:
            n = Nd[d] - Nds.get((d, s), 0)
            if n > 0:
                vals.append((Sd[d] - Sds.get((d, s), 0.0)) / n)
        m = math.fsum(vals) / len(vals) if vals else -math.inf
        if m < worst:
            worst, wsym = m, s
    tot = math.fsum(bys.values())
    top = max(bys.values()) / tot if (bys and tot > 0) else math.inf
    if tiers:
        tm = max(sorted(tiers), key=lambda t: len(tiers[t]))
        cl = [v for _, v in PN.cluster_series(tiers[tm], "net_base")[0]]
        tmean = math.fsum(cl) / len(cl) if cl else None
    else:
        tm, tmean = None, None
    return {"loso_min": worst, "loso_worst": wsym, "top_share": top, "tier_major": tm, "tier_major_mean": tmean}


def _wilson_lo(k, n, z=1.6448536269514722):
    if n == 0:
        return 0.0
    ph = k / n
    den = 1 + z * z / n
    return (ph + z * z / (2 * n) - z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / den


def _corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((v - ma) ** 2 for v in a))
    sb = math.sqrt(sum((v - mb) ** 2 for v in b))
    if sa == 0 or sb == 0:
        return 0.0
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa * sb)


def info_effect(pos, cpos):
    """Gross information effect: mean over common active days of (gross cluster of the signal positions - gross
    cluster of the control positions). Costs cancel, so it measures information, not economics (plateau input)."""
    a = dict(PN.cluster_series(pos, "gross")[0])
    b = dict(PN.cluster_series(cpos, "gross")[0])
    d = [a[k] - b[k] for k in a if k in b]
    return S.mean(d) if d else None


def control_positions(rows, rbs, hz_ms):
    ckey = "ctrl" if any("ctrl" in r for r in rows) else None
    cflags = PN.signal_flags(rows, ckey) if ckey else {(r["sym"], r["t_ms"]): 1 for r in rows if r["elig"]}
    return PN.build_positions(rbs, cflags, hz_ms)


def neighbours(plan: dict | None, plan_id: str):
    """P2-D0 grid neighbours: planned cells of the same hypothesis whose params differ in exactly one key."""
    if not plan:
        return None
    ix = {t["plan_id"]: t for t in plan["trials"]}
    me = ix.get(plan_id)
    if me is None:
        return None
    out = []
    for t in plan["trials"]:
        if t["hypothesis"] != me["hypothesis"] or t["plan_id"] == plan_id:
            continue
        diff = [k for k in me["params"] if t["params"].get(k) != me["params"][k]]
        if len(diff) == 1:
            out.append(t["plan_id"])
    return sorted(out)


def core_summary(battery: Battery, ev: dict) -> dict:
    """Round-context entry for one evaluated trial, computed exactly as the battery does: the net-alpha p (raw),
    the net alpha, the aligned alpha day series (0 on a day without factor data) and the gross information effect."""
    c = ev["candidate"]
    hz_ms = PN.HORIZON_MS[c["horizon"]]
    blk, lag = battery._blk(c["horizon"])
    vdays = sorted(ev["window"]["validation_days"])
    rows, _ = _purge(ev)
    rbs = PN.by_symbol(rows)
    pos = PN.build_positions(rbs, PN.signal_flags(rows), hz_ms)
    fac = PN.day_factors(rows)
    adays = [d for d in vdays if d in fac]
    pm = dict(zip(vdays, PN.portfolio_series(pos, "net_base", vdays)))
    p_ser, m_ser = [pm[d] for d in adays], [fac[d][1] for d in adays]
    out = {"trial_id": c["trial_id"], "plan_id": c["plan_id"], "hypothesis": c["hypothesis"], "p": None,
           "alpha": None, "series": [0.0] * len(vdays),
           "info_effect": info_effect(pos, control_positions(rows, rbs, hz_ms))}
    if len(adays) >= 3 and pos:
        al = battery._alpha(p_ser, m_ser, blk, lag, c["trial_id"], "alpha")
        amap = dict(zip(adays, al["series"]))
        out.update({"p": al["p"], "alpha": al["alpha"], "series": [amap.get(d, 0.0) for d in vdays]})
    return out


def round_context(summaries: list, *, total_trials: int, exclude: str | None = None) -> dict:
    """Context for evaluating one candidate (``exclude`` = its trial id) against its round."""
    fam = {s["plan_id"]: s["p"] for s in summaries if s["trial_id"] != exclude}
    rs = {s["trial_id"]: s["series"] for s in summaries if s["trial_id"] != exclude}
    nm = {s["plan_id"]: s["info_effect"] for s in summaries}
    return {"family_p": fam, "round_series": rs, "neighbour_info_effects": nm,
            "ledger_counts": {"total_trials": total_trials}}
