from shared.telegram_messages import (
    closed_message, opened_message, risk_halted_message, runtime_status_message,
    target_message,
)


def test_opened_message_is_explicitly_an_actual_trade():
    text = opened_message({
        'id': 42, 'symbol': 'BTCUSDT', 'trade_type': 'momentum',
        'timeframe': '15m', 'is_paper_trade': True, 'entry_price': 100,
        'stop_loss': 97, 'target_1': 103, 'target_2': 105, 'target_3': 107,
    }, 50)
    assert 'فُتحت صفقة' in text
    assert 'ورقية' in text
    assert 'ليست مجرد إشارة' in text


def test_target_message_explains_new_protection():
    text = target_message({
        'id': 7, 'symbol': 'ETHUSDT', 'entry_price': 100,
        'stop_loss': 100, 'target_1': 101.25, 'target_2': 103,
        'target_3': 105, 'opened_at': None,
    }, 1, 101.25, 50, 0.3)
    assert 'T1' in text
    assert 'التعادل الصافي' in text
    assert 'T1✅' in text
    assert 'T2🎯' in text
    assert 'الصافي:' in text


def test_closed_message_reports_gross_cost_and_net_separately():
    text = closed_message({
        'active_trade_id': 7, 'symbol': 'ETHUSDT', 'entry_price': 100,
        'exit_price': 100.3, 'profit_percent': 0.3, 'profit_usdt': 0.15,
        'notes': 'break_even', 'target_reached': 1, 'duration_hours': 2,
    }, roundtrip_cost_pct=0.3, trade_amount=50)
    assert 'الإجمالي: +0.30%' in text
    assert 'التكلفة المقدرة: -0.30%' in text
    assert 'تعادل صافٍ: +0.00%' in text


def test_risk_halt_message_explains_trigger_and_continued_monitoring():
    text = risk_halted_message({
        'reason': 'loss_streak_halt', 'consecutive_losses': 7,
        'loss_halt_limit': 7, 'daily_pnl_pct': -1.2,
        'weekly_pnl_pct': -2.3, 'drawdown_pct': 3.4,
    })
    assert '7/7 خسائر' in text
    assert 'فتح صفقات جديدة' in text
    assert 'ستبقى تحت المتابعة' in text


def test_runtime_recovery_message_reports_restored_symbols():
    text = runtime_status_message('tracker.recovered', {
        'count': 2, 'symbols': ['BTCUSDT', 'ETHUSDT'],
        'websocket_enabled': True,
    })
    assert '2' in text
    assert 'BTCUSDT, ETHUSDT' in text
    assert 'مفعّل' in text
