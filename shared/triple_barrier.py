"""
TripleBarrier — وحدة خروج موحّدة مشتركة بين trade_tracker الحيّ والباكتيستر
=============================================================================
مصدر حقيقة واحد لمنطق الخروج: TP1/TP2/TP3 + break-even + trailing stop + expiry.
الإصدار 1.0 — 2026-05-16

الاستخدام:
    from shared.triple_barrier import TripleBarrierConfig, TripleBarrierState, TripleBarrierResult
    from shared.triple_barrier import create_config_from_trade, step_barrier

    # تهيئة بإعدادات الصفقة
    cfg = create_config_from_trade(trade_dict)
    state = TripleBarrierState(peak=cfg.entry)

    # خطوة لكل شمعة (الباكتيستر) أو كل فحص (trade_tracker)
    result = step_barrier(cfg, state, high, low, close, hours_elapsed)
    if result is not None:
        # الصفقة أُغلقت — result يحتوي كل التفاصيل
        pass
    else:
        # الصفقة لا تزال مفتوحة — state تحدّثت
        pass
"""

from dataclasses import dataclass, field
from typing import Optional


# ── الإعدادات الثابتة ─────────────────────────────────────────────────────
TRAIL_STOP_PCT_DEFAULT = 2.5     # % trailing stop تحت القمة (بعد T2)
TRADE_EXPIRY_H_DEFAULT = 48.0    # ساعة إغلاق إجباري
T1_EXPIRY_H_DEFAULT    = 24.0    # ساعة إغلاق عند توقف عند T1 فقط
NO_T1_EXPIRY_H_DEFAULT = 24.0    # ساعة إغلاق إن لم يصل T1
TRADE_AMOUNT_DEFAULT   = 50.0    # USDT لكل صفقة
STOP_SLIPPAGE_DEFAULT  = 0.001   # 0.1% تعبئة أسوأ عند أي stop
ROUNDTRIP_COST_DEFAULT = 0.003   # 0.3% رسوم/انزلاق عام خارج stop-fill

TIMEFRAME_EXPIRY_HOURS = {
    '15m': (48.0, 24.0, 12.0),
    '4h': (96.0, 48.0, 24.0),
    '1d': (240.0, 120.0, 72.0),
}


def expiry_policy_for_timeframe(timeframe: str | None) -> tuple[float, float, float]:
    """Return max, T1-stall and no-T1 hours for newly opened trades."""
    return TIMEFRAME_EXPIRY_HOURS.get(
        str(timeframe or '').lower(),
        (TRADE_EXPIRY_H_DEFAULT, T1_EXPIRY_H_DEFAULT, NO_T1_EXPIRY_H_DEFAULT),
    )


@dataclass
class TripleBarrierConfig:
    """
    إعدادات الصفقة الثابتة — لا تتغير طوال عمر الصفقة.
    """
    symbol:          str
    entry:           float
    target_1:        float
    target_2:        float
    target_3:        float
    stop_loss:       float
    trade_amount:    float = TRADE_AMOUNT_DEFAULT
    trail_stop_pct:  float = TRAIL_STOP_PCT_DEFAULT
    expiry_h:        float = TRADE_EXPIRY_H_DEFAULT
    t1_expiry_h:     float = T1_EXPIRY_H_DEFAULT
    no_t1_expiry_h:  float = NO_T1_EXPIRY_H_DEFAULT
    stop_slippage:   float = STOP_SLIPPAGE_DEFAULT
    roundtrip_cost:  float = ROUNDTRIP_COST_DEFAULT

    def validate(self) -> Optional[str]:
        """يعيد رسالة خطأ إن كانت الإعدادات غير صالحة، وإلا None."""
        if self.target_1 <= self.entry:
            return f"T1 ({self.target_1}) <= entry ({self.entry})"
        if self.target_2 <= self.entry:
            return f"T2 ({self.target_2}) <= entry ({self.entry})"
        if self.target_3 <= self.entry:
            return f"T3 ({self.target_3}) <= entry ({self.entry})"
        if self.stop_loss >= self.entry:
            return f"SL ({self.stop_loss}) >= entry ({self.entry})"
        if self.stop_loss <= 0:
            return f"SL ({self.stop_loss}) <= 0"
        if not self.target_1 < self.target_2 < self.target_3:
            return "targets must be strictly ordered T1 < T2 < T3"
        if not 0 <= self.stop_slippage < 1:
            return f"invalid stop slippage ({self.stop_slippage})"
        if not 0 <= self.roundtrip_cost < 1:
            return f"invalid roundtrip cost ({self.roundtrip_cost})"
        return None

    def net_break_even_stop(self) -> float:
        """Stop level whose modeled fill covers the external round-trip cost."""
        required = self.entry * (1 + self.roundtrip_cost) / (1 - self.stop_slippage)
        # A stop cannot be placed above the already observed T1 price.
        return min(self.target_1, required)


@dataclass
class TripleBarrierState:
    """
    الحالة المتغيرة للصفقة — تتحدث مع كل شمعة/فحص.
    """
    peak:           float        # أعلى سعر بلغته الصفقة
    highest_target: int  = 0    # أعلى هدف تحقق (0/1/2/3)
    hours_open:     float = 0.0  # إجمالي الوقت المفتوح (بالساعات)

    def effective_stop(self, cfg: TripleBarrierConfig) -> tuple:
        """
        يحسب الستوب الفعّال ونوعه حسب الحالة الحالية.
        يعيد (stop_price, stop_label).
        """
        if self.highest_target >= 2:
            trail = self.peak * (1 - cfg.trail_stop_pct / 100)
            price = max(cfg.target_1, trail)
            return price, f"trailing@{price:.6f}(قمة {self.peak:.6f})"
        elif self.highest_target >= 1:
            price = cfg.net_break_even_stop()
            return price, f"net_break_even@{price:.6f}"
        else:
            return cfg.stop_loss, f"SL_أصلي@{cfg.stop_loss:.6f}"


@dataclass
class TripleBarrierResult:
    """
    نتيجة إغلاق الصفقة — يُعاد من step_barrier عند الإغلاق.
    """
    result:         str    # 'WIN' | 'LOSS'
    exit_price:     float
    profit_pct:     float
    profit_usdt:    float
    duration_h:     float
    exit_reason:    str    # 'T3'|'break_even'|'trailing_stop'|'stop_loss'|'T1_expired_24h'|'expired_48h'
    target_reached: int    # أعلى هدف تحقق
    stop_hit:       bool   # هل الخروج كان بضرب الستوب (بالمفهوم الأصلي — SL الأصلي)


def create_config_from_trade(
    trade: dict, trade_amount: float = TRADE_AMOUNT_DEFAULT,
    stop_slippage: float = STOP_SLIPPAGE_DEFAULT,
    roundtrip_cost: float = ROUNDTRIP_COST_DEFAULT,
) -> TripleBarrierConfig:
    """
    ينشئ TripleBarrierConfig من صف active_trades (dict).
    يقبل حقول من DB مباشرة.
    """
    return TripleBarrierConfig(
        symbol       = trade['symbol'],
        entry        = float(trade['entry_price']),
        target_1     = float(trade['target_1']),
        target_2     = float(trade['target_2']),
        target_3     = float(trade['target_3']),
        stop_loss    = float(trade['stop_loss']),
        trade_amount = trade_amount,
        stop_slippage = stop_slippage,
        roundtrip_cost = roundtrip_cost,
        expiry_h = float(trade.get('expiry_h') or TRADE_EXPIRY_H_DEFAULT),
        t1_expiry_h = float(trade.get('t1_expiry_h') or T1_EXPIRY_H_DEFAULT),
        no_t1_expiry_h = float(trade.get('no_t1_expiry_h') or NO_T1_EXPIRY_H_DEFAULT),
    )


def create_state_from_trade(trade: dict) -> TripleBarrierState:
    """
    ينشئ TripleBarrierState من صف active_trades (dict) — للصفقات المفتوحة.
    يستخدم peak_price إن وُجد.
    """
    entry = float(trade['entry_price'])
    peak  = float(trade.get('peak_price') or entry)
    peak  = max(peak, entry)  # لا تقل عن entry
    return TripleBarrierState(
        peak           = peak,
        highest_target = int(trade.get('highest_target_hit') or 0),
        hours_open     = 0.0,  # يُحسب خارجياً ويُمرَّر عبر hours_elapsed
    )


def step_barrier(
    cfg:           TripleBarrierConfig,
    state:         TripleBarrierState,
    high:          float,
    low:           float,
    close:         float,
    hours_elapsed: float = 1.0,   # الوقت المنقضي منذ آخر فحص (1.0 لشمعة 1h)
    stop_observation_price: float | None = None,
) -> Optional[TripleBarrierResult]:
    """
    يُطبّق منطق TripleBarrier على شمعة/لحظة واحدة.
    يُحدّث state ويعيد TripleBarrierResult عند الإغلاق، وإلا يعيد None.

    عند غياب بيانات tick نستخدم ترتيباً محافظاً: الستوب القائم عند بداية الشمعة
    يسبق أهداف الشمعة، ثم نحدّث الأهداف ونفحص الستوب الديناميكي الجديد، ثم T3
    والانتهاء. يمنع هذا منح ربح متفائل حين تلمس الشمعة الوقف والهدف معاً.
    """
    # ── 1. الستوب القائم قبل أحداث الشمعة (hard-stop priority) ─────────────
    prior_stop, prior_label = state.effective_stop(cfg)
    if low <= prior_stop:
        stop_reference = (min(prior_stop, stop_observation_price)
                          if stop_observation_price is not None else prior_stop)
        return _stop_result(
            cfg, state, stop_reference, prior_label, hours_elapsed)

    # ── 2. تحديث القمة ─────────────────────────────────────────────────────
    if high > state.peak:
        state.peak = high

    # ── 3. تحديث الأهداف ───────────────────────────────────────────────────
    if high >= cfg.target_3 and state.highest_target < 3:
        state.highest_target = 3
    elif high >= cfg.target_2 and state.highest_target < 2:
        state.highest_target = 2
    elif high >= cfg.target_1 and state.highest_target < 1:
        state.highest_target = 1

    # ── 4. تحديث ساعات الفتح ──────────────────────────────────────────────
    state.hours_open += hours_elapsed

    # ── 5. T3: أمر الهدف يُملأ لحظة بلوغه؛ الستوب السابق فُحص أعلاه ───────
    if state.highest_target == 3:
        profit_pct  = ((cfg.target_3 - cfg.entry) / cfg.entry) * 100
        profit_usdt = (profit_pct / 100) * cfg.trade_amount
        return TripleBarrierResult(
            result         = 'WIN',
            exit_price     = cfg.target_3,
            profit_pct     = round(profit_pct, 4),
            profit_usdt    = round(profit_usdt, 4),
            duration_h     = round(state.hours_open, 2),
            exit_reason    = 'T3',
            target_reached = 3,
            stop_hit       = False,
        )

    # ── 6. الستوب الديناميكي الناتج عن T1/T2 داخل الشمعة ─────────────────
    eff_stop, stop_label = state.effective_stop(cfg)

    if low <= eff_stop:
        stop_reference = (min(eff_stop, stop_observation_price)
                          if stop_observation_price is not None else eff_stop)
        return _stop_result(cfg, state, stop_reference, stop_label, 0.0)

    # ── 7. انتهاء 24h عند T1 فقط ─────────────────────────────────────────
    if state.hours_open >= cfg.t1_expiry_h and state.highest_target == 1:
        profit_pct  = ((close - cfg.entry) / cfg.entry) * 100
        profit_usdt = (profit_pct / 100) * cfg.trade_amount
        is_win      = close > cfg.entry
        return TripleBarrierResult(
            result         = 'WIN' if is_win else 'LOSS',
            exit_price     = round(close, 8),
            profit_pct     = round(profit_pct, 4),
            profit_usdt    = round(profit_usdt, 4),
            duration_h     = round(state.hours_open, 2),
            exit_reason    = 'T1_expired_24h',
            target_reached = state.highest_target,
            stop_hit       = False,
        )

    if state.hours_open >= cfg.no_t1_expiry_h and state.highest_target == 0:
        return _expiry_result(cfg, state, close, f'no_T1_expired_{int(cfg.no_t1_expiry_h)}h')

    # ── 8. انتهاء الصلاحية الكلية ─────────────────────────────────────────
    if state.hours_open >= cfg.expiry_h:
        return _expiry_result(cfg, state, close, f'expired_{int(cfg.expiry_h)}h')

    # الصفقة لا تزال مفتوحة
    return None


def _stop_result(cfg, state, stop, _label, hours_elapsed):
    state.hours_open += hours_elapsed
    exit_price, profit_pct = modeled_stop_exit(cfg.entry, stop, cfg.stop_slippage)
    profit_usdt = (profit_pct / 100) * cfg.trade_amount
    is_win = exit_price > cfg.entry
    reason = ('trailing_stop' if state.highest_target >= 2
              else 'break_even' if state.highest_target == 1 else 'stop_loss')
    return TripleBarrierResult(
        'WIN' if is_win else 'LOSS', round(exit_price, 8), round(profit_pct, 4),
        round(profit_usdt, 4), round(state.hours_open, 2), reason,
        state.highest_target, (not is_win) and exit_price <= cfg.stop_loss,
    )


def _expiry_result(cfg, state, close, reason):
    profit_pct = ((close - cfg.entry) / cfg.entry) * 100
    return TripleBarrierResult(
        'WIN' if close > cfg.entry else 'LOSS', round(close, 8), round(profit_pct, 4),
        round((profit_pct / 100) * cfg.trade_amount, 4), round(state.hours_open, 2),
        reason, state.highest_target, False,
    )


def barrier_status_summary(cfg: TripleBarrierConfig, state: TripleBarrierState, current_price: float) -> str:
    """
    ملخص حالة الصفقة — للتسجيل في اللوقات.
    """
    eff_stop, stop_label = state.effective_stop(cfg)
    pnl_pct = ((current_price - cfg.entry) / cfg.entry) * 100
    return (
        f"{cfg.symbol} | "
        f"السعر: {current_price:.6f} | "
        f"PnL: {pnl_pct:+.2f}% | "
        f"أعلى هدف: T{state.highest_target} | "
        f"الستوب الفعّال: {stop_label} | "
        f"المدة: {state.hours_open:.1f}h"
    )


def modeled_stop_exit(entry: float, eff_stop: float, slippage: float) -> tuple:
    """Model a stop fill AT the stop level, not at an overshot poll price.

    Returns (fill_price, profit_pct). Slippage is subtracted so the fill is
    slightly worse than the stop, never better. When eff_stop is above entry
    (a trailing stop in profit), the result is still a win — the sign is
    carried by fill_price vs entry (the win/loss determination is done by the caller).
    """
    if entry <= 0 or eff_stop <= 0:
        raise ValueError("entry and stop must be positive")
    if not 0 <= slippage < 1:
        raise ValueError("slippage must be in [0, 1)")
    fill_price = eff_stop * (1 - slippage)
    profit_pct = ((fill_price - entry) / entry) * 100
    return fill_price, profit_pct
