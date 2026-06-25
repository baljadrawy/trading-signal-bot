# تصميم: جامع + متعلّم حي (Live-Learning Signal Collector)

**التاريخ:** 2026-06-25
**المشروع:** trading-signal-bot (Paper Trading فقط)
**الحالة:** معتمد التصميم — بانتظار مراجعة المواصفات ثم خطة التنفيذ

---

## 1. الهدف والسياق

أثبتت أبحاث 2026-06 (باكتيست 595 عملة × 9 سنوات + تدقيق عدائي) أن لا حافة تاريخية قابلة للنشر،
وأن الحافة الوحيدة المكتشفة كانت **تعرّض-نظام-سوق مركّزاً في 6 أشهر** (غير ممثِّل للدورة الحالية).
لذا التحوّل: **التوقّف عن الاعتماد على التاريخ**، وبناء نظام **يجمع صفقات paper حيّة بمؤشرات بسيطة شفّافة
+ سياق ماكرو (BTC/ETH/USDT.D)**، ويعمل **مفتوحاً بلا توقّف**، **ويتعلّم باستمرار** من الدورة الحالية.

**مبدأ:** الـ100 صفقة = حدّ إحماء قبل أول تعلّم، وليست نقطة توقّف. التعلّم متجدّد على نافذة متحرّكة.

**نطاق هذه المواصفة:** الجامع + الماكرو + التسجيل + بوابة التعلّم المستمرّة. **خارج النطاق:** ML معقّد،
أي مال حقيقي (يبقى `PAPER_TRADING=true`).

---

## 2. المعمارية (مكوّنات مستقلة بواجهات واضحة)

```
Scanner (كما هو) ──> مرشّحون
      │
      ▼
SimpleEntry (جديد، يحلّ محلّ _calculate_scores)  ── لكل (عملة، إطار): يُرجع trade_type أو None
      │
      ▼
MacroContext (جديد) ── snapshot + state + should_block()
      │
      ▼
SignalEngine (مُعدّل: بوابة خفيفة + استشارة learned_gates + تسجيل كامل)
      │
      ▼
signals (+ trade_type, macro_snapshot)  ──> trade_tracker (كما هو) ──> trade_results
      │
      ▼
ContinuousLearner (كرون، جديد) ── نافذة متحرّكة (type × macro × tf) → learned_gates
```

**الأطر الزمنية:** `15m, 4h, 1d` (الإطار بُعد تعلّم).

---

## 3. المكوّنات بالتفصيل

### 3.1 MacroContext (`shared/macro_context.py` — جديد)
**الغرض:** يوفّر سياق السوق الكلّي ويُقرّر حجب الإشارات في الحالات القصوى.
**المصادر:**
- BTC/ETH: Binance klines 4h لـ `BTCUSDT`/`ETHUSDT` (نفس عميل الأنلايزر). الاتجاه = السعر مقابل EMA50(4h)
  + تغيّر 3 أيام (18 شمعة 4h). الحالات: `strong_bearish | bearish | neutral | bullish | strong_bullish`
  (يُعاد استخدام منطق `btc_trend` في Scanner للاتّساق).
- USDT.D / BTC.D: CoinGecko `GET /api/v3/global` (هيمنة حيّة). يُخزَّن snapshot يومي في `macro_history`،
  ويُحسب `usdtd_trend` = إشارة (القيمة الآن − متوسط 3 أيام): `rising | falling | flat`، و`rising_fast`
  إذا الصعود > `USDTD_SPIKE_PP` نقطة مئوية مطلقة خلال 3 أيام (افتراضي 0.5).
**التخزين المؤقت:** ساعة واحدة (يحترم حدود CoinGecko المجانية).
**الواجهة:**
- `snapshot() -> dict`: `{btc_change_pct, eth_change_pct, usdt_d, btc_d, usdtd_3d_delta}`
- `state() -> dict`: `{btc_trend, eth_trend, usdtd_trend}`
- `should_block() -> bool`: `True` إذا `btc_trend == 'strong_bearish'` **أو** `usdtd_trend == 'rising_fast'`.
**معالجة الأخطاء:** فشل CoinGecko → استخدم آخر cache؛ غياب تاريخ كافٍ → `usdtd_trend='flat'` (لا نحجب لنقص بيانات).

### 3.2 SimpleEntry (`analyzer/simple_entry.py` — جديد؛ يُستبدل به استدعاء _calculate_scores في وضع التعلّم)
**الغرض:** محرّك دخول بسيط شفّاف لكل (عملة، إطار) على **شموع مغلقة**.
**المحرّكان (long فقط، paper):**
- `momentum`: `close > ema20 > ema50` **و** `close > max(high لآخر 20 شمعة مغلقة سابقة)` (اختراق قمة) **و** `volume > 1.2 × sma(volume,20)`.
- `reversion`: `rsi14 < 35` **و** `close > close[-1]` (ارتداد) **و** `close < bb_lower × 1.01` (قرب الباند السفلي).
**الإرجاع:** `'momentum' | 'reversion' | None`. إذا أطلق الاثنان → `'momentum'` (الأولوية). كل العتبات معاملات قابلة للضبط.
**المستويات:** تُحسب بـ `_calculate_levels` الحالي (ATR) — بلا تغيير.

### 3.3 تغييرات قاعدة البيانات (`database/migrate_live_learning_2026_06_25.sql`)
- `signals`: `ADD COLUMN trade_type VARCHAR`, `ADD COLUMN macro_snapshot JSONB`.
- جدول جديد `macro_history(date DATE PK, usdt_d NUMERIC, btc_d NUMERIC, btc_trend VARCHAR, eth_trend VARCHAR)`.
- جدول جديد `learned_gates(trade_type VARCHAR, macro_state VARCHAR, timeframe VARCHAR, n INT, wr NUMERIC,
  expectancy NUMERIC, weight NUMERIC, updated_at TIMESTAMP, PRIMARY KEY(trade_type, macro_state, timeframe))`.
  - `macro_state` = تمثيل مُكثَّف، افتراضي `usdtd_trend` (مثلاً `usdtd_falling`) لإبقاء الخلايا قابلة للتعبئة.

### 3.4 SignalEngine (مُعدّل: `signal_engine/signal_logic.py`)
في وضع `LIVE_LEARNING_MODE`:
1. إذا `MacroContext.should_block()` → لا إشارات (حماية).
2. لكل مرشّح أطلق محرّكاً: استشر `learned_gates.weight` للخليّة `(trade_type × macro_state × tf)`:
   - إحماء (لا صفّ أو `n < MIN_CELL_N`) → وزن محايد = **يُسمح**.
   - `weight <= THROTTLE` (خليّة خاسرة مُتعلَّمة) → **يُحجب/يُخفَّض**.
   - غير ذلك → يُسمح.
3. تُبقى cooldowns الخفيفة (per-symbol 2h) لمنع التركيز؛ يُخفّف inter-signal (معامل) لتسريع الجمع.
4. **تسجيل كامل** دائماً: `trade_type`, `macro_snapshot`, الإطار، قيم المؤشرات البسيطة.
الفلاتر القديمة (score الـ5، bullish/volatile/4h-ban/stoch-gate) **مُعطّلة** في هذا الوضع.

### 3.5 trade_tracker — **بلا تغيير** (يسجّل target_reached/stop_hit/الربح كما هو).

### 3.6 ContinuousLearner (`research/continuous_learner.py` + كرون — جديد)
**الغرض:** التعلّم المتجدّد. **الجدولة:** كل 12–24س.
**المنطق:**
- إذا (الصفقات المغلقة ≥ `WARMUP_N`=100):
  - لكل خليّة `(trade_type × macro_state × tf)` على **آخر `ROLL_N`=150 صفقة مغلقة**: احسب `n, wr, expectancy`
    (صافي الرسوم).
  - حدّث `learned_gates`: `weight` دالة في `expectancy` (مثلاً `+1` رابح، `0` محايد، `throttle` خاسر).
  - **حُرّاس:** خليّة `n < MIN_CELL_N`=10 → وزن محايد (لا نتصرّف على عيّنة صغيرة). نافذة متحرّكة فقط (تتبع الدورة).
- يكتب تقرير Telegram موجزاً بأفضل/أسوأ الخلايا.
**النتيجة:** البوابة (3.4) تستهلك `learned_gates` → تكيّف ذاتي مستمرّ.

---

## 4. تدفّق البيانات
Scanner → مرشّحون → SimpleEntry(per tf) → MacroContext(block?/snapshot) → SignalEngine(gate via learned_gates + record)
→ signals(+type,+macro) → trade_tracker → trade_results → ContinuousLearner(rolling) → learned_gates → (يغذّي البوابة).

## 5. معالجة الأخطاء
- CoinGecko فشل/حدود → cache أخير؛ نقص تاريخ → `flat` (لا حجب). Binance فشل → معالجة الأنلايزر الحالية.
- ContinuousLearner: يتخطّى الخلايا الصغيرة؛ لا يكتب أوزاناً متطرّفة (clamp).

## 6. الاختبار
- وحدة: `MacroContext.state/should_block` على fixtures؛ محرّكا SimpleEntry على شموع مُعدّة؛ تجميع
  ContinuousLearner على صفقات مُعدّة (تحقّق من النافذة المتحرّكة + حدّ العيّنة).
- تكامل: تشغيل دورة كاملة على بيانات حيّة (paper) والتأكّد من تسجيل type+macro وتوليد إشارات.

## 7. الإطلاق والتراجع
- خلف علم `LIVE_LEARNING_MODE=true` في `.env` (الوضع القديم يبقى متاحاً بإيقافه).
- ترحيل SQL للأعمدة/الجداول. إعادة بناء الحاويات المتأثّرة (analyzer/signal_engine/cron) بـ `--no-cache`.
- **يبقى `PAPER_TRADING=true`.** التراجع = `LIVE_LEARNING_MODE=false`.

## 8. المعاملات (افتراضات قابلة للضبط)
`TIMEFRAMES_LL=15m,4h,1d` · `MOM_BREAKOUT_N=20` · `MOM_VOL_MULT=1.2` · `REV_RSI=35` ·
`USDTD_SPIKE_PP=0.5` · `MACRO_CACHE_HOURS=1` · `WARMUP_N=100` · `ROLL_N=150` · `MIN_CELL_N=10` ·
`THROTTLE_EXPECTANCY=0` · `LEARN_CRON_HOURS=12`.

## 9. حدود المرحلة
داخل: الجامع + الماكرو + التسجيل + التعلّم بالبوابة على نافذة متحرّكة.
خارج: ML/أوزان مؤشرات معقّدة، تنفيذ حقيقي، أكثر من long.
