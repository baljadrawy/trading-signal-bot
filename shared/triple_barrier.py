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
TRADE_AMOUNT_DEFAULT   = 50.0    # USDT لكل صفقة


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
        return None


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
            return cfg.entry, f"break_even@{cfg.entry:.6f}"
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


def create_config_from_trade(trade: dict, trade_amount: float = TRADE_AMOUNT_DEFAULT) -> TripleBarrierConfig:
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
) -> Optional[TripleBarrierResult]:
    """
    يُطبّق منطق TripleBarrier على شمعة/لحظة واحدة.
    يُحدّث state ويعيد TripleBarrierResult عند الإغلاق، وإلا يعيد None.

    ملاحظة الترتيب: نتحقق T3 → trailing/break-even stop → expiry.
    القمة تُحدَّث أولاً (قبل الفحوصات) لضمان استخدام أعلى قيمة.
    """
    # ── 1. تحديث القمة ─────────────────────────────────────────────────────
    if high > state.peak:
        state.peak = high

    # ── 2. تحديث الأهداف ───────────────────────────────────────────────────
    if high >= cfg.target_3 and state.highest_target < 3:
        state.highest_target = 3
    elif high >= cfg.target_2 and state.highest_target < 2:
        state.highest_target = 2
    elif high >= cfg.target_1 and state.highest_target < 1:
        state.highest_target = 1

    # ── 3. تحديث ساعات الفتح ──────────────────────────────────────────────
    state.hours_open += hours_elapsed

    # ── 4. فحص T3 — إغلاق فوري بالربح الأقصى ───────────────────────────
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

    # ── 5. الستوب الديناميكي ──────────────────────────────────────────────
    eff_stop, stop_label = state.effective_stop(cfg)

    if low <= eff_stop:
        # خروج عند الستوب الديناميكي
        # NOTE: this backtest path books stops at the exact stop (no slippage). The LIVE tracker (trade_tracker) and the measurement oracle apply STOP_SLIPPAGE via modeled_stop_exit(). This asymmetry is deliberate and left for a future unify-slippage decision — do not "fix" silently.
        exit_price  = eff_stop
        profit_pct  = ((exit_price - cfg.entry) / cfg.entry) * 100
        profit_usdt = (profit_pct / 100) * cfg.trade_amount
        is_win      = exit_price > cfg.entry
        # تحديد نوع الإغلاق
        if state.highest_target >= 2:
            reason = 'trailing_stop'
        elif state.highest_target == 1:
            reason = 'break_even'
        else:
            reason = 'stop_loss'
        # stop_hit = true فقط عند الستوب الأصلي (بخسارة)
        original_stop_hit = (not is_win) and (exit_price <= cfg.stop_loss)
        return TripleBarrierResult(
            result         = 'WIN' if is_win else 'LOSS',
            exit_price     = round(exit_price, 8),
            profit_pct     = round(profit_pct, 4),
            profit_usdt    = round(profit_usdt, 4),
            duration_h     = round(state.hours_open, 2),
            exit_reason    = reason,
            target_reached = state.highest_target,
            stop_hit       = original_stop_hit,
        )

    # ── 6. انتهاء 24h عند T1 فقط ─────────────────────────────────────────
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

    # ── 7. انتهاء الصلاحية الكلية ─────────────────────────────────────────
    if state.hours_open >= cfg.expiry_h:
        profit_pct  = ((close - cfg.entry) / cfg.entry) * 100
        profit_usdt = (profit_pct / 100) * cfg.trade_amount
        is_win      = close > cfg.entry
        return TripleBarrierResult(
            result         = 'WIN' if is_win else 'LOSS',
            exit_price     = round(close, 8),
            profit_pct     = round(profit_pct, 4),
            profit_usdt    = round(profit_usdt, 4),
            duration_h     = round(state.hours_open, 2),
            exit_reason    = f'expired_{int(cfg.expiry_h)}h',
            target_reached = state.highest_target,
            stop_hit       = False,
        )

    # الصفقة لا تزال مفتوحة
    return None


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
    fill_price = eff_stop * (1 - slippage)
    profit_pct = ((fill_price - entry) / entry) * 100
    return fill_price, profit_pct
