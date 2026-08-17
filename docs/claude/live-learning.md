# وضع التعلّم الحي (Live-Learning) — النظام الحالي

> النظام النشط منذ 2026-06-26 (paper). يجمع صفقات حيّة بمؤشرات بسيطة + سياق ماكرو، ويتعلّم باستمرار من الدورة الحالية. خلف العلم `LIVE_LEARNING_MODE=true`. الخلفية والمبرّر: [strategy-history.md](strategy-history.md). المواصفة/الخطة: `docs/superpowers/specs|plans/2026-06-25-live-learning-collector*`.

## التدفّق
محرّك دخول بسيط (analyzer) → بوابة ماكرو خفيفة (signal_engine) → موافقة آلية بالسياسة (خدمة claude_review، من دون استدعاء Claude) → تسجيل كامل في `signals` → trade_tracker → continuous_learner → `learned_gates` (يغذّي البوابة).

## المكوّنات
- **`analyzer/simple_entry.py`** — محرّكان (long، شمعة مغلقة):
  - `momentum`: close > ema20 > ema50 + اختراق قمة 20 شمعة سابقة + حجم > 1.2× المتوسط.
  - `reversion`: rsi14 < 35 + ارتداد قرب الباند السفلي.
  - يُوسَم في `analysis_data['trade_type']` (momentum/reversion/None).
- **`shared/macro_context.py`** — BTC/ETH (Binance، مفاتيح فارغة، klines عامة) + USDT.D/BTC.D (CoinGecko `/global`)، تخزين مؤقت ساعة، يكتب `macro_history`.
  - **`should_block()`** يحجب فقط إذا: BTC `strong_bearish` **أو** USDT.D `rising_fast` (≥ USDTD_SPIKE_PP نقطة مئوية خلال 3 أيام).
  - `macro_state_key()` = `usdtd_<trend>` (يجب أن يطابق المتعلّم والبوابة).
- **`signal_engine` (find_best_signal_live)** — يحجب على الماكرو؛ يخنق خلايا `learned_gates` ذات `weight<=0 & n>=MIN_CELL_N`؛ يسجّل `trade_type` + `macro_snapshot`.
- **`claude_review`** — في هذا الوضع **السياسة توافق آليًا ولا يُستدعى Claude**؛ تُسجّل الإشارة `decision_source=policy_auto`. خارج الوضع تسجّل مراجعة النموذج `decision_source=claude`، والفشل المغلق `system_fail_closed`.
- **`research/continuous_learner.py`** (خدمة كرون كل `LEARN_CRON_HOURS`=24س):
  - يرسل **ملخّصاً يومياً** على Telegram دائماً (ماكرو + الجمع + تقدّم الإحماء + أفضل خلية).
  - عند ≥ `WARMUP_N`=100 صفقة **موسومة مغلقة**: يحسب لكل خليّة (نوع × usdtd_state × إطار) على نافذة `ROLL_N`=150 → `weight`؛ يخنق الخاسرة (expectancy ≤ THROTTLE) بشرط `n ≥ MIN_CELL_N`=10. نافذة متحرّكة تتبع الدورة الحالية.
  - كل دفعة تمر بتحقق صارم للأبعاد والقيم والعينة. الدفعة غير الصالحة تسجّل `rejected` في `learning_runs` ولا تغيّر البوابات.
  - كل إدراج/تعديل/تقادم يسجل القديم والجديد في `learned_gate_history` مع `strategy_version`.
  - التدريب والتقارير القياسية تستبعد التاريخ الملوّث وتبدأ من `LEARNING_CLEAN_START=2026-07-20`.
  - لا تُخنق خلية لمجرد أن متوسطها سالب؛ يجب أن يكون الحد الأعلى لفترة الثقة 95% غير موجب.
  - الخلايا المخنوقة تمر باستكشاف ثابت بالساعة بنسبة `LEARNING_EXPLORATION_RATE=10%` لمنع حلقة الانحياز الذاتي.

## التراجع عن دفعة تعلم

اعرض التشغيلات أولًا ثم نفّذ rollback لمعرّف تشغيل مطبق. العملية ذرّية وتسجل كتغيير جديد:

```bash
docker exec -i postgres psql -U trading_signal_bot -d trading_signals \
  -c "SELECT id,status,strategy_version,trade_count,cell_count,completed_at FROM learning_runs ORDER BY id DESC;"
docker compose exec continuous_learner python research/rollback_learned_gates.py RUN_ID
```

## المعاملات (config.py / .env)
`TIMEFRAMES_LL=15m,4h,1d` · `MOM_BREAKOUT_N=20` · `MOM_VOL_MULT=1.2` · `REV_RSI=35` ·
`USDTD_SPIKE_PP=0.5` · `MACRO_CACHE_HOURS=1` · `WARMUP_N=100` · `ROLL_N=150` ·
`MIN_CELL_N=10` · `THROTTLE_EXPECTANCY=0` · `LEARN_CRON_HOURS=24`.

حوكمة التعلم: `LEARNING_CLEAN_START=2026-07-20T00:00:00` ·
`LEARNING_CONFIDENCE_Z=1.96` · `LEARNING_EXPLORATION_RATE=0.10`.

## ملاحظات تشغيلية
- الأهداف/الستوب: `_calculate_levels` (ATR) + triple-barrier في trade_tracker بلا تغيير.
- عند `LIVE_LEARNING_MODE=false`: يعود المسار القديم بالكامل (الوصف في [strategy-history.md](strategy-history.md)).
- الاختبارات: `research/skill_application/.venv/bin/python -m pytest tests/ -q` (14 اختبار وحدة).
- مراقبة الجمع: راجع أوامر psql في [database.md](database.md).
