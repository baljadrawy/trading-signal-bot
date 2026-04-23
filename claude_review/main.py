"""
Claude Review - يراجع الإشارات قبل إرسالها
"""
import asyncio
import json
import sys
sys.path.append('/app')

import anthropic
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.alerts import send_alert
from shared.retry_utils import format_error, is_network_error, compute_backoff, alert_threshold

logger = setup_logger('claude_review')

async def main():
    logger.info("🚀 بدء تشغيل Claude Review...")
    await Database.connect()

    claude_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    
    consecutive_errors = 0

    try:
        while True:
            try:
                signals = await Database.fetch("""
                    SELECT id, symbol, timeframe, market_condition,
                           entry_price, target_1, target_2, target_3,
                           stop_loss, score, score_details
                    FROM signals
                    WHERE (claude_approved IS NULL OR claude_approved = false)
                    AND (claude_comment IS NULL OR claude_comment = '')
                    AND signal_time > NOW() - INTERVAL '2 hours'
                    ORDER BY signal_time DESC
                """)

                for signal in signals:
                    await review_signal(claude_client, dict(signal))

                consecutive_errors = 0
                await asyncio.sleep(15)

            except Exception as e:
                consecutive_errors += 1
                network = is_network_error(e)
                wait = compute_backoff(consecutive_errors, network)
                msg = f"❌ خطأ في Claude Review ({consecutive_errors}): {format_error(e)}"
                if network:
                    logger.warning(msg)
                else:
                    logger.error(msg)
                if consecutive_errors >= alert_threshold(network):
                    await send_alert(
                        f"Claude Review فشل {consecutive_errors} مرات متتالية\nالخطأ: {format_error(e)[:200]}",
                        level='critical', component='ClaudeReview'
                    )
                await asyncio.sleep(wait)
                
    finally:
        await Database.disconnect()

async def review_signal(client: anthropic.Anthropic, signal: dict):
    """مراجعة إشارة واحدة بواسطة Claude"""
    try:
        score_details = signal['score_details']
        if isinstance(score_details, str):
            score_details = json.loads(score_details)
        
        # حساب نسبة المخاطرة/المكافأة
        entry = float(signal['entry_price'])
        stop = float(signal['stop_loss'])
        t1 = float(signal['target_1'])
        risk = entry - stop
        reward = t1 - entry
        rr_ratio = reward / risk if risk > 0 else 0
        
        # جلب عدد Timeframes المؤكدة من score_details
        confirmed_tfs = score_details.get('confirmed_timeframes', [signal['timeframe']])
        tf_count = score_details.get('timeframe_confirmations', 1)

        t1_pct = (float(signal['target_1']) - entry) / entry * 100
        t2_pct = (float(signal['target_2']) - entry) / entry * 100
        sl_pct = (stop - entry) / entry * 100

        prompt = f"""أنت محلل تداول صارم. هدفك رفع نسبة الربح، لذا ارفض الإشارات المشكوك فيها.

نظام التسجيل الجديد (بعد إعادة بناء 2026-04-22):
- 3 مؤشرات نشطة فقط (mean-reverting): rsi, bollinger, stoch_rsi — كل واحد يعطي 0 إلى 1 نقطة
- مكافأة إضافية من order_book و BTC trend
- المفاتيح التالية في score_details دائماً 0 (المؤشرات معطّلة عمداً — لا تعتبرها نقطة ضعف):
  macd, ema_cross, volume, obv, btc_trend
- نطاق النقاط الفعلي: 0 إلى ~3.5 (وليس 0-10)
- قيمة النقاط {signal['score']} هنا مقبولة لأنها بالفعل تجاوزت عتبة النظام

الإشارة:
- العملة: {signal['symbol']} | الإطار الرئيسي: {signal['timeframe']}
- حالة السوق: {signal['market_condition']}
- النقاط: {signal['score']}
- الإطارات المؤكِّدة: {tf_count} إطار — {', '.join(confirmed_tfs)}
- تفاصيل المؤشرات: {json.dumps(score_details, indent=2, ensure_ascii=False)}

مستويات التداول:
- دخول: {entry} | SL: {stop} ({sl_pct:.2f}%)
- T1: {signal['target_1']} ({t1_pct:.2f}%) | T2: {signal['target_2']} ({t2_pct:.2f}%)
- R:R = {rr_ratio:.2f}

معايير الرفض (ارفض فقط إذا تحقق واحدة من هذه):
1. R:R < 1.0 (مخاطرة بلا عائد)
2. حالة السوق = volatile (تاريخياً 34% win rate)
3. عدد الإطارات المؤكِّدة < 2
4. كل المؤشرات الثلاثة النشطة (rsi, bollinger, stoch_rsi) = 0 أو أقل من 0.3

وافق في كل حالة أخرى. لا تنظر إلى المؤشرات المعطّلة كسبب للرفض.

الشكل المطلوب (بدون أي نص إضافي):
DECISION: APPROVED أو REJECTED
REASON: [سبب محدد بجملة واحدة، اذكر الرقم إذا رفضت]"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Haiku أسرع وأرخص للمراجعة
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = response.content[0].text
        approved = "APPROVED" in response_text
        reason = ""
        
        if "REASON:" in response_text:
            reason = response_text.split("REASON:")[-1].strip()
        
        # تحديث قاعدة البيانات
        await Database.execute("""
            UPDATE signals
            SET claude_approved = $1, claude_comment = $2
            WHERE id = $3
        """, approved, reason, signal['id'])
        
        status = "✅ موافق" if approved else "❌ مرفوض"
        logger.info(f"{status} على إشارة {signal['symbol']} - {reason[:50]}")
        
    except Exception as e:
        logger.error(f"خطأ في مراجعة الإشارة {signal['id']}: {e}")
        # fail-open: عند فشل API نوافق على الإشارة (لتجنب توقف البوت)
        # البيانات أثبتت أن claude_review لم يحسّن النتائج تاريخياً (37.8% win rate)
        await Database.execute(
            "UPDATE signals SET claude_approved = true, claude_comment = $1 WHERE id = $2",
            f'موافقة تلقائية - فشل API: {str(e)[:100]}',
            signal['id']
        )
        await send_alert(
            f"Claude Review API failure — موافقة تلقائية على {signal['symbol']}\nالخطأ: {str(e)[:150]}",
            level='warning', component='ClaudeReview'
        )

if __name__ == "__main__":
    asyncio.run(main())
