"""التعلّم الحي المستمرّ: نافذة متحرّكة → أوزان learned_gates لكل (نوع × ماكرو × إطار)."""
import asyncio
import json
import math
import statistics
from collections import defaultdict
from datetime import timedelta
from shared.config import config
from shared.database import Database
from shared.logger import setup_logger
from shared.health import mark_started, mark_success, mark_failure
from shared.schema import require_schema
from shared.learning_governance import validate_cells
try:
    from shared.alerts import send_alert
except Exception:
    send_alert = None
try:
    from shared.macro_context import classify_usdtd_trend, should_block
except Exception:
    classify_usdtd_trend = None
    should_block = None

logger = setup_logger('continuous_learner')


async def send_status_digest():
    """ملخّص حالة يومي إلى Telegram: ماكرو + جمع الإشارات + تقدّم الإحماء + خلايا التعلّم.
    يُرسَل دائماً (حتى أثناء الإحماء) قبل منطق التعلّم."""
    # ── الماكرو ──
    mrows = await Database.fetch(
        "SELECT date, usdt_d, btc_d, btc_trend, eth_trend FROM macro_history ORDER BY date DESC LIMIT 4")
    # خرائط ترجمة لصيغة بسيطة ومفهومة
    TR = {'strong_bearish': 'هابط بقوة 🔻', 'bearish': 'هابط 🔴', 'neutral': 'محايد ⚪',
          'sideways': 'عرضي ⚪', 'bullish': 'صاعد 🟢', 'strong_bullish': 'صاعد بقوة 🟢'}
    UD = {'flat': 'مستقرّة', 'rising': 'ترتفع', 'rising_fast': 'ترتفع بسرعة ⚠️',
          'falling': 'تنخفض', 'n/a': '—'}
    TF = {'15m': '15 دقيقة', '1h': 'ساعة', '4h': '4 ساعات', '1d': 'يومي'}
    TT = {'momentum': 'زخم (شراء قوة)', 'reversion': 'ارتداد (شراء تشبّع)'}

    if mrows:
        latest = mrows[0]
        usdt_now = float(latest['usdt_d'] or 0)
        prior = [float(r['usdt_d']) for r in mrows[1:] if r['usdt_d'] is not None]
        avg_3d = (sum(prior) / len(prior)) if prior else usdt_now
        usdtd_trend = (classify_usdtd_trend(usdt_now, avg_3d, config.USDTD_SPIKE_PP)
                       if classify_usdtd_trend else 'n/a')
        blocking = (should_block((latest['btc_trend'] or 'neutral'), usdtd_trend)
                    if should_block else False)
        gate = ("🔴 متوقّف مؤقتاً — السوق هابط بقوة" if blocking
                else "🟢 يلتقط الإشارات الآن")
        macro_line = (f"🌍 حالة السوق:\n"
                      f"• بيتكوين: {TR.get(latest['btc_trend'], latest['btc_trend'])}  |  "
                      f"إيثيريم: {TR.get(latest['eth_trend'], latest['eth_trend'])}\n"
                      f"• هيمنة USDT: {usdt_now:.2f}% ({UD.get(usdtd_trend, usdtd_trend)})\n"
                      f"• البوت: {gate}")
    else:
        macro_line = "🌍 حالة السوق: لا بيانات بعد"
    # ── جمع الإشارات ──
    total_tagged = await Database.fetchval(
        "SELECT COUNT(*) FROM signals WHERE trade_type IS NOT NULL") or 0
    byrows = await Database.fetch(
        "SELECT trade_type, timeframe, COUNT(*) c FROM signals WHERE trade_type IS NOT NULL GROUP BY 1,2")
    by_type, by_tf = {}, {}
    for r in byrows:
        by_type[r['trade_type']] = by_type.get(r['trade_type'], 0) + r['c']
        by_tf[r['timeframe']] = by_tf.get(r['timeframe'], 0) + r['c']
    type_line = " | ".join(f"{TT.get(k, k)}: {v}" for k, v in by_type.items()) or "—"
    tf_line = " | ".join(f"{TF.get(k, k)}: {v}" for k, v in by_tf.items()) or "—"
    closed = await Database.fetchval(
        """SELECT COUNT(*) FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
           WHERE s.trade_type IS NOT NULL AND tr.exit_time >= $1::text::timestamp""",
        config.LEARNING_CLEAN_START) or 0
    collect_line = (f"🎯 الإشارات المجموعة: {total_tagged} صفقة\n"
                    f"• النوع: {type_line}\n• الأطر: {tf_line}")
    # ── التعلّم ──
    lg = await Database.fetch(
        "SELECT trade_type, macro_state, timeframe, n, wr, expectancy, weight,ci_low,ci_high FROM learned_gates "
        "WHERE n>=$1 AND ci_low IS NOT NULL AND ci_high IS NOT NULL ORDER BY expectancy DESC",
        config.MIN_CELL_N)
    if lg:
        throttled = sum(1 for r in lg if float(r['weight'] or 0) <= 0)
        t = lg[0]
        ud_key = (t['macro_state'] or '').replace('usdtd_', '')
        lg_line = (f"🧠 التعلّم: يعمل ({len(lg)} تركيبة، أوقف {throttled} خاسرة)\n"
                   f"🏆 الأفضل: {TT.get(t['trade_type'], t['trade_type'])} + هيمنة USDT {UD.get(ud_key, ud_key)} "
                   f"+ {TF.get(t['timeframe'], t['timeframe'])}\n"
                   f"   ربح صافٍ {float(t['expectancy']):+.2f}%/صفقة "
                   f"(95% CI [{float(t['ci_low']):+.2f}, {float(t['ci_high']):+.2f}])، "
                   f"نجاح {float(t['wr']):.0f}% ({t['n']} صفقة)")
    else:
        remaining = max(0, config.WARMUP_N - closed)
        lg_line = (f"🧠 التعلّم: لم يبدأ بعد\n"
                   f"• أُغلقت {closed} من {config.WARMUP_N} صفقة (باقٍ {remaining} ليبدأ)")
    msg = ("📊 تقرير البوت اليومي (تداول ورقي)\n\n"
           + macro_line + "\n\n" + collect_line + "\n\n" + lg_line)
    logger.info(msg)
    if send_alert:
        try:
            await send_alert(msg, level='info', component='LiveLearning')
        except Exception as e:
            logger.warning(f"digest send failed: {e}")


def compute_cells(trades, min_cell_n: int, throttle_expectancy: float,
                  fee_roundtrip: float = 0.0, confidence_z: float = 1.96):
    """توقّع الخلية = متوسط الربح الصافي (إجمالي − رسوم الذهاب والإياب).
    `profit_percent` المخزَّن إجماليٌّ بلا رسوم؛ نطرح fee_roundtrip هنا فالبوابة تخنق
    على أساس صافٍ لا إجمالي (إصلاح العطب: خلية إجماليها بين 0 والرسوم كانت تبقى weight=1
    رغم خسارتها صافياً). المخزَّن في learned_gates.expectancy صافٍ أيضاً، فالتقرير اليومي
    لا يتوّج خلية خاسرة صافياً كـ«رابحة». fee_roundtrip=0.0 يحفظ التوافق الخلفي."""
    groups = defaultdict(list)
    for t in trades:
        groups[(t['trade_type'], t['macro_state'], t['timeframe'])].append(t)
    out = []
    for (tt, ms, tf), items in groups.items():
        n = len(items)
        wins = sum(1 for x in items if x['is_win'])
        net_returns = [float(x['profit_percent']) - fee_roundtrip for x in items]
        net_exp = sum(net_returns) / n
        if n >= 2:
            margin = confidence_z * statistics.stdev(net_returns) / math.sqrt(n)
            ci_low, ci_high = net_exp - margin, net_exp + margin
        else:
            ci_low, ci_high = -math.inf, math.inf
        # Fail open: throttle only when even the optimistic confidence bound is non-positive.
        weight = 0.0 if n >= min_cell_n and ci_high <= throttle_expectancy else 1.0
        timestamps = [x.get('exit_time') for x in items if x.get('exit_time') is not None]
        out.append({'trade_type': tt, 'macro_state': ms, 'timeframe': tf,
                    'n': n, 'wr': round(wins / n * 100, 1), 'expectancy': round(net_exp, 4),
                    'ci_low': round(ci_low, 4) if math.isfinite(ci_low) else None,
                    'ci_high': round(ci_high, 4) if math.isfinite(ci_high) else None,
                    'sample_start': min(timestamps) if timestamps else None,
                    'sample_end': max(timestamps) if timestamps else None,
                    'weight': weight})
    return out


def select_stale_throttles(rows, now, stale_days):
    """تُعيد مفاتيح (نوع، ماكرو، إطار) للخلايا المخنوقة المتقادمة لحذفها (إعادة فحص دوري).

    خليّة مخنوقة (weight<=0) توقّفت عن إنتاج صفقات → لا يعيد المُتعلّم حسابها →
    يبقى صفّها يحجب إلى الأبد (حظر ذاتي التحقّق). الحل: أي خليّة مخنوقة لم تُحدَّث
    منذ `stale_days` تُحذف فتعود إحماءً (لا صفّ = لا حجب) وتُجرَّب بعيّنة جديدة.
    الخلايا المسموحة (weight>0) لا تُمسّ — لا تحجب أصلاً. المقارنة صارمة (< لا <=)
    فالعتبة تماماً لا تُحذف. `rows`: dicts فيها weight و updated_at (datetime)."""
    cutoff = now - timedelta(days=stale_days)
    return [(r['trade_type'], r['macro_state'], r['timeframe'])
            for r in rows
            if r['weight'] is not None and r['weight'] <= 0 and r['updated_at'] < cutoff]


async def run():
    await Database.connect()
    await require_schema('continuous_learner')
    await mark_started('continuous_learner')
    try:
        await _run_learning_cycle()
        await mark_success('continuous_learner')
    except Exception as exc:
        await mark_failure('continuous_learner', exc)
        if send_alert:
            await send_alert(
                f"Continuous Learner cycle failed\n{type(exc).__name__}: {str(exc)[:200]}",
                level='critical', component='LiveLearning')
        raise


async def _run_learning_cycle():
    closed = await Database.fetchval(
        """SELECT COUNT(*) FROM trade_results tr JOIN signals s ON tr.signal_id=s.id
           WHERE s.trade_type IS NOT NULL AND tr.exit_time >= $1::text::timestamp""",
        config.LEARNING_CLEAN_START)
    # ── التعلّم أولاً (يحدّث learned_gates) ثم نرسل التقرير ليعكس الخلايا الطازجة ──
    if (closed or 0) >= config.WARMUP_N:
        rows = await Database.fetch(
            """SELECT s.trade_type, s.macro_snapshot, s.timeframe, tr.profit_percent,
                      (tr.result='WIN') AS is_win, tr.exit_time
               FROM trade_results tr JOIN signals s ON tr.signal_id = s.id
               WHERE s.trade_type IS NOT NULL AND tr.exit_time >= $2::text::timestamp
               ORDER BY tr.exit_time DESC LIMIT $1""",
            config.ROLL_N, config.LEARNING_CLEAN_START)
        trades = []
        for r in rows:
            ms = r['macro_snapshot'] or {}
            if isinstance(ms, str):
                ms = json.loads(ms)
            trades.append({'trade_type': r['trade_type'],
                           'macro_state': f"usdtd_{ms.get('usdtd_trend', 'flat')}",
                           'timeframe': r['timeframe'], 'profit_percent': r['profit_percent'],
                           'is_win': r['is_win'], 'exit_time': r['exit_time']})
        cells = compute_cells(trades, config.MIN_CELL_N, config.THROTTLE_EXPECTANCY,
                              config.FEE_ROUNDTRIP_PCT, config.LEARNING_CONFIDENCE_Z)
        errors = validate_cells(cells, trade_count=len(trades), min_cell_n=config.MIN_CELL_N)
        parameters = {'roll_n': config.ROLL_N, 'min_cell_n': config.MIN_CELL_N,
                      'throttle_expectancy': config.THROTTLE_EXPECTANCY,
                      'fee_roundtrip_pct': config.FEE_ROUNDTRIP_PCT}
        parameters.update({'clean_start': config.LEARNING_CLEAN_START,
                           'confidence_z': config.LEARNING_CONFIDENCE_Z,
                           'exploration_rate': config.LEARNING_EXPLORATION_RATE})
        if errors:
            await Database.execute(
                """INSERT INTO learning_runs(strategy_version,status,trade_count,cell_count,parameters,
                                                validation_errors,completed_at)
                   VALUES($1,'rejected',$2,$3,$4::jsonb,$5::jsonb,NOW())""",
                config.APP_VERSION, len(trades), len(cells), json.dumps(parameters), json.dumps(errors))
            raise ValueError('invalid learning batch: ' + '; '.join(errors[:5]))

        async with Database.acquire() as conn:
            async with conn.transaction():
                run_id = await conn.fetchval(
                    """INSERT INTO learning_runs(strategy_version,status,trade_count,cell_count,parameters)
                       VALUES($1,'validating',$2,$3,$4::jsonb) RETURNING id""",
                    config.APP_VERSION, len(trades), len(cells), json.dumps(parameters))
                for c in cells:
                    old = await conn.fetchrow(
                        """SELECT trade_type,macro_state,timeframe,n,wr,expectancy,weight,
                                  ci_low,ci_high,sample_start,sample_end,
                                  strategy_version,learning_run_id FROM learned_gates
                           WHERE trade_type=$1 AND macro_state=$2 AND timeframe=$3 FOR UPDATE""",
                        c['trade_type'], c['macro_state'], c['timeframe'])
                    await conn.execute(
                        """INSERT INTO learned_gates
                               (trade_type,macro_state,timeframe,n,wr,expectancy,weight,
                                ci_low,ci_high,sample_start,sample_end,
                                strategy_version,learning_run_id,updated_at)
                           VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                           ON CONFLICT (trade_type,macro_state,timeframe) DO UPDATE
                           SET n=$4,wr=$5,expectancy=$6,weight=$7,ci_low=$8,ci_high=$9,
                               sample_start=$10,sample_end=$11,strategy_version=$12,
                               learning_run_id=$13,updated_at=NOW()""",
                        c['trade_type'], c['macro_state'], c['timeframe'], c['n'], c['wr'],
                        c['expectancy'], c['weight'], c['ci_low'], c['ci_high'],
                        c['sample_start'], c['sample_end'], config.APP_VERSION, run_id)
                    new_value = {**c, 'strategy_version': config.APP_VERSION,
                                 'learning_run_id': run_id}
                    await conn.execute(
                        """INSERT INTO learned_gate_history
                               (learning_run_id,action,trade_type,macro_state,timeframe,
                                old_value,new_value,strategy_version)
                           VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8)""",
                        run_id, 'update' if old else 'insert', c['trade_type'], c['macro_state'],
                        c['timeframe'], json.dumps(dict(old), default=str) if old else None,
                        json.dumps(new_value, default=str), config.APP_VERSION)
                await conn.execute(
                    "UPDATE learning_runs SET status='applied',completed_at=NOW() WHERE id=$1", run_id)
        losers = [c for c in cells if c['weight'] == 0]
        logger.info(f"📚 Learner: {len(cells)} cells, {len(losers)} throttled (تفاصيلها في التقرير اليومي)")
        # ── إعادة الفحص الدوري: احذف الخلايا المخنوقة المتقادمة فتعود إحماءً ──
        grows = await Database.fetch(
            "SELECT trade_type, macro_state, timeframe, weight, updated_at FROM learned_gates")
        db_now = await Database.fetchval("SELECT NOW()::timestamp")  # naive، يطابق عمود updated_at (بلا منطقة)
        stale = select_stale_throttles([dict(r) for r in grows], db_now, config.THROTTLE_STALE_DAYS)
        for tt, ms, tf in stale:
            async with Database.acquire() as conn:
                async with conn.transaction():
                    old = await conn.fetchrow(
                        "SELECT * FROM learned_gates WHERE trade_type=$1 AND macro_state=$2 AND timeframe=$3 FOR UPDATE",
                        tt, ms, tf)
                    if old:
                        await conn.execute(
                            "DELETE FROM learned_gates WHERE trade_type=$1 AND macro_state=$2 AND timeframe=$3",
                            tt, ms, tf)
                        await conn.execute(
                            """INSERT INTO learned_gate_history
                                   (learning_run_id,action,trade_type,macro_state,timeframe,old_value,strategy_version)
                               VALUES($1,'expire',$2,$3,$4,$5::jsonb,$6)""",
                            old['learning_run_id'], tt, ms, tf,
                            json.dumps(dict(old), default=str), config.APP_VERSION)
        if stale:
            logger.info(
                f"♻️ تقادم: حُذفت {len(stale)} خليّة مخنوقة متقادمة (>{config.THROTTLE_STALE_DAYS}ي) → تعود إحماءً")
    else:
        logger.info(f"warm-up: {closed}/{config.WARMUP_N} closed trades; skipping learning")
    # التقرير اليومي يُرسَل أخيراً ليعكس learned_gates المحدّثة (لا رسالة منفصلة مكرّرة)
    try:
        await send_status_digest()
    except Exception as e:
        logger.warning(f"status digest failed: {e}")


if __name__ == "__main__":
    asyncio.run(run())
