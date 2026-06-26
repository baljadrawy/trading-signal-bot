# وضع التعلّم الحي (Live-Learning) — النظام الحالي

> النظام النشط منذ 2026-06-26 (paper). يجمع صفقات حيّة بمؤشرات بسيطة + سياق ماكرو، ويتعلّم باستمرار من الدورة الحالية. خلف العلم `LIVE_LEARNING_MODE=true`. الخلفية والمبرّر: [strategy-history.md](strategy-history.md). المواصفة/الخطة: `docs/superpowers/specs|plans/2026-06-25-live-learning-collector*`.

## التدفّق
محرّك دخول بسيط (analyzer) → بوابة ماكرو خفيفة (signal_engine) → موافقة تلقائية (claude_review) → تسجيل كامل في `signals` → trade_tracker → continuous_learner → `learned_gates` (يغذّي البوابة).

## المكوّنات
- **`analyzer/simple_entry.py`** — محرّكان (long، شمعة مغلقة):
  - `momentum`: close > ema20 > ema50 + اختراق قمة 20 شمعة سابقة + حجم > 1.2× المتوسط.
  - `reversion`: rsi14 < 35 + ارتداد قرب الباند السفلي.
  - يُوسَم في `analysis_data['trade_type']` (momentum/reversion/None).
- **`shared/macro_context.py`** — BTC/ETH (Binance، مفاتيح فارغة، klines عامة) + USDT.D/BTC.D (CoinGecko `/global`)، تخزين مؤقت ساعة، يكتب `macro_history`.
  - **`should_block()`** يحجب فقط إذا: BTC `strong_bearish` **أو** USDT.D `rising_fast` (≥ USDTD_SPIKE_PP نقطة مئوية خلال 3 أيام).
  - `macro_state_key()` = `usdtd_<trend>` (يجب أن يطابق المتعلّم والبوابة).
- **`signal_engine` (find_best_signal_live)** — يحجب على الماكرو؛ يخنق خلايا `learned_gates` ذات `weight<=0 & n>=MIN_CELL_N`؛ يسجّل `trade_type` + `macro_snapshot`.
- **`claude_review`** — **يوافق تلقائياً** في هذا الوضع (تجاوز المعايير الانعكاسية القديمة لجمع نزيه).
- **`research/continuous_learner.py`** (خدمة كرون كل `LEARN_CRON_HOURS`=24س):
  - يرسل **ملخّصاً يومياً** على Telegram دائماً (ماكرو + الجمع + تقدّم الإحماء + أفضل خلية).
  - عند ≥ `WARMUP_N`=100 صفقة **موسومة مغلقة**: يحسب لكل خليّة (نوع × usdtd_state × إطار) على نافذة `ROLL_N`=150 → `weight`؛ يخنق الخاسرة (expectancy ≤ THROTTLE) بشرط `n ≥ MIN_CELL_N`=10. نافذة متحرّكة تتبع الدورة الحالية.

## المعاملات (config.py / .env)
`TIMEFRAMES_LL=15m,4h,1d` · `MOM_BREAKOUT_N=20` · `MOM_VOL_MULT=1.2` · `REV_RSI=35` ·
`USDTD_SPIKE_PP=0.5` · `MACRO_CACHE_HOURS=1` · `WARMUP_N=100` · `ROLL_N=150` ·
`MIN_CELL_N=10` · `THROTTLE_EXPECTANCY=0` · `LEARN_CRON_HOURS=24`.

## ملاحظات تشغيلية
- الأهداف/الستوب: `_calculate_levels` (ATR) + triple-barrier في trade_tracker بلا تغيير.
- عند `LIVE_LEARNING_MODE=false`: يعود المسار القديم بالكامل (الوصف في [strategy-history.md](strategy-history.md)).
- الاختبارات: `research/skill_application/.venv/bin/python -m pytest tests/ -q` (14 اختبار وحدة).
- مراقبة الجمع: راجع أوامر psql في [database.md](database.md).
