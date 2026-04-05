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

logger = setup_logger('claude_review')

async def main():
    logger.info("🚀 بدء تشغيل Claude Review...")
    await Database.connect()
    
    claude_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    
    try:
        while True:
            try:
                # جلب الإشارات التي تحتاج مراجعة
                signals = await Database.fetch("""
                    SELECT id, symbol, timeframe, market_condition,
                           entry_price, target_1, target_2, target_3,
                           stop_loss, score, score_details
                    FROM signals
                    WHERE claude_approved IS NULL
                    AND signal_time > NOW() - INTERVAL '1 hour'
                    ORDER BY signal_time DESC
                """)
                
                for signal in signals:
                    await review_signal(claude_client, dict(signal))
                
                await asyncio.sleep(15)
                
            except Exception as e:
                logger.error(f"❌ خطأ في Claude Review: {e}")
                await asyncio.sleep(30)
                
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
        
        prompt = f"""أنت محلل تداول خبير. راجع هذه الإشارة وقرر الموافقة أو الرفض.

العملة: {signal['symbol']}
الإطار الزمني: {signal['timeframe']}
حالة السوق: {signal['market_condition']}
النقاط الإجمالية: {signal['score']}/10

تفاصيل المؤشرات:
{json.dumps(score_details, indent=2, ensure_ascii=False)}

مستويات التداول:
- سعر الدخول: {entry}
- الهدف الأول: {signal['target_1']} ({((float(signal['target_1'])-entry)/entry*100):.2f}%)
- الهدف الثاني: {signal['target_2']} ({((float(signal['target_2'])-entry)/entry*100):.2f}%)
- الهدف الثالث: {signal['target_3']} ({((float(signal['target_3'])-entry)/entry*100):.2f}%)
- وقف الخسارة: {stop} ({((stop-entry)/entry*100):.2f}%)
- نسبة المخاطرة/المكافأة: {rr_ratio:.2f}

قرر بـ APPROVED أو REJECTED مع سبب مختصر باللغة العربية.
الشكل المطلوب:
DECISION: APPROVED/REJECTED
REASON: [السبب بجملة أو جملتين]"""

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
        # في حالة الخطأ، نوافق تلقائياً لا نوقف النظام
        await Database.execute(
            "UPDATE signals SET claude_approved = true, claude_comment = 'تمت الموافقة تلقائياً - خطأ في API' WHERE id = $1",
            signal['id']
        )

if __name__ == "__main__":
    asyncio.run(main())
