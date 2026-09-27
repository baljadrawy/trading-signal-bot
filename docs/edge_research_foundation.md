# Edge Research Foundation

هذه الطبقة مختبر Offline فقط. لا تستدعي Binance أو Telegram أو Claude، ولا تقرأ أو
تكتب جداول التشغيل. وهي لا تثبت وجود Edge ولا تعدّل أي قاعدة تداول.

## 1. Dataset snapshot

يجب أن تكون ملفات المصدر محلية وتحتوي OHLCV وحقول `symbol`, `timeframe`,
`timestamp`, `close_time`. معلومات القرار التاريخية مثل `quote_volume`, `change_24h_pct`,
`macro_pass`, `spread`, و`spread_data_mode` يجب أن تكون Point-in-Time.

أنشئ spec JSON يحتوي `sources`, `source_name`, `start_time`, `end_time`, `symbols`,
`timeframes`, `row_counts`, `git_sha`, `universe`, `universe_completeness`, و`source_metadata`، ثم:

```bash
python -m research.replay create-dataset --spec dataset_spec.json
python -m research.replay verify-dataset --dataset research/datasets/<dataset_id>
```

`dataset_id` مشتق من المحتوى والـmetadata. الملفات تنسخ إلى مجلد جديد وتصبح read-only.
أي اختلاف ينتج ID جديداً؛ checksum mismatch يفشل التحقق.

## 2. Point-in-Time universe

كل سجل Universe يدعم:

```text
symbol, listed_at, delisted_at, eligible_from, eligible_until, quote_asset, status
```

ويجب إعلان أحد مستويات الاكتمال:

- `FULL_POINT_IN_TIME`
- `PARTIAL_POINT_IN_TIME`
- `CURRENT_SURVIVORS_ONLY`

آخر حالتين لا تسمحان بوصف النتائج بأنها Survivorship-safe.

## 3. Replay

```bash
python -m research.replay run \
  --dataset research/datasets/<dataset_id> \
  --config research/replay_config.example.json \
  --output research/runs
```

المسار هو: snapshot → quality gates → Universe-at-t → المؤشرات المشتركة مع الإنتاج →
regime → entry → stop/targets → spread/macro/risk decision → fixed execution ranking →
entry fill adapter → production barrier → partial accounting → artifacts.

كل قرار يستخدم شموعاً `close_time <= decision_time`. الزمن الداخلي UTC. `signal_time`
هو إغلاق شمعة القرار، و`entry_eligible_time` هو أول وقت بعد اكتمالها. `fill_time` يسجل
أول تعبئة يمكن إثباتها من البيانات التالية.

## 4. Opportunity set

يسجل كل `symbol × timeframe × decision_time` بعد توفر الحد الأدنى، بما فيه المرفوض.
الـID حتمي من dataset/symbol/timeframe/time/version. يسجل Context والسيولة والميزات
وحالة شروط Momentum/Reversion والماكرو والكون والمخاطر والقرار النهائي وكود الرفض.

## 5. Features vs labels

`features` لا تقبل أسماء مستقبلية. اختبار Leakage يفشل عند `future_*`, `MFE`, `MAE`,
أو `future_label`. القيم المستقبلية تحفظ حصراً في `labels` بعد القرار: عوائد 1/3/6/12/24
شمعة، MFE/MAE، زمن كل منهما، وMFE/MAE قبل T1 عندما يتوفر.

## 6. Position state machine

الحالات المسجلة: `OPEN → T1_FILLED → T2_FILLED → T3_FILLED/CLOSED`. الدالة الإنتاجية
`step_barrier` هي مصدر أولوية الوقف وBE وTrailing وExpiries. المحاسبة تستخدم الدالة
الإنتاجية `fills_between` لتوزيع 25/50/25 ودمج الشرائح دون minimum notional.

في `CONSERVATIVE` يسبق الوقف القائم الهدف عند اجتماع الاثنين. في `AMBIGUOUS` تسجل
`intrabar_sequence_unknown` وتستبعد الصفقة افتراضياً من المقاييس الحساسة.

## 7. Costs and execution metadata

النموذج يفصل entry fee وexit fee وspread وslippage، مع Baseline مجموعها 0.30%، ويطبق
0.10% إضافية على تعبئة الوقف عبر دالة الإنتاج. كل manifest يسجل fill/intrabar/fee/
slippage/spread models. لا يجوز استخدام spread حالي؛ المقبول هو historical orderbook أو
proxy معلن. `NO_SPREAD_DATA` يرفض القرار fail-closed.

## 8. Experiment and reproducibility

كل Run يسجل dataset ID، Git SHA، dirty state، config hash، contract hash، seed،
assumptions، counts، warnings، quality وparity. العقد يشمل Parameters وSHA-256 لملفات
المنطق. اختلاف أي منهما يظهر كـ`RESEARCH CONTRACT DOES NOT MATCH LIVE CONTRACT`.

النتيجة تسمى Reproducible فقط مع dataset/config/SHA/seed متطابقة وworking tree نظيف،
ومخرجات byte-identical. HOLDOUT مقفول افتراضياً ولا يفتح إلا بخيار صريح.

## 9. Artifacts

كل Run ينشئ مجلداً immutable يحتوي:

```text
manifest.json, config.json, dataset_manifest.json, strategy_contract.json,
opportunities.jsonl, trades.jsonl, trade_events.jsonl,
equity_curve.jsonl, metrics.json, quality_report.json, parity_report.json
```

البيانات الكبيرة وRuns مستبعدة من Git. `research/schema.sql` مخطط اختياري موثق فقط؛
لا يطبق على Production.

## 10. القيود الحالية

- Historical delisted universe غير مكتمل ما لم يورده Dataset خارجي موثق.
- Historical orderbook/spread غير متوفر تلقائياً.
- USDT dominance التاريخي يجب توريده؛ لا يستخدم النظام حالة الماكرو الحالية.
- OHLC لا يثبت ترتيب أحداث intrabar.
- تعبئة WebSocket الدقيقة لا يمكن استعادتها بلا ticks؛ fill model يظهر في manifest.
- لا توجد Golden DB snapshots ملتزمة بالمستودع، لذلك parity مع صفقات حية تاريخية يبقى غير منفذ.
- العقد الحالي لا يملك عينة Forward كافية.

هذه المخرجات ليست إثبات Edge. لا يجوز استخدام HOLDOUT في Discovery، أو اعتبار Proxy
spread حقيقة، أو خلط Runs ذات contract hashes مختلفة، أو استخدام Forward labels في القرار.
