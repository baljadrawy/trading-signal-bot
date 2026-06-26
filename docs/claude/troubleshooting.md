# المشاكل الشائعة وحلولها

### الـ Dockerfile لا ينسخ الكود
بعض الحاويات بلا volume mount. كل Dockerfile يجب أن يحوي:
```dockerfile
COPY shared/ ./shared/
COPY service_name/ ./
```
**القاعدة:** استخدم `--no-cache` دائماً عند بناء image بعد تعديل الكود.

### signal_engine يكرّر العملات المرفوضة
SQL في `signal_engine/main.py` يستثني `symbol_blacklist` و`active_trades`.

### `datetime` غير معرّف في trade_tracker
`from datetime import datetime, timezone` في أعلى الملف (لا داخل دالة).

### MAX_SIGNALS_PER_DAY يوقف البوت
القيمة 5 توقفه بعد 5 إشارات. استخدم `MAX_SIGNALS_PER_DAY=0`؛ الكود يتحقق `if config.MAX_SIGNALS_PER_DAY > 0`.

### target_1 أقل من entry_price
`_calculate_levels` تتحقّق `stop_loss < entry` و`targets > entry` بعد الحساب.

### تكرار الصفقات في /trades
`DISTINCT ON (symbol)` في query الـ active_trades.

### خطأ mutable default list في dataclass
`field(default_factory=lambda: os.getenv('TIMEFRAMES','15m,4h,1d').split(','))` بدل قائمة مباشرة.

### setup_logger يفشل خارج Docker
`shared/logger.py` يلفّ إنشاء file handler بـ `try/except OSError` فيتراجع لـ console عند غياب `/app/logs` (تشغيل اختبارات على المضيف).
