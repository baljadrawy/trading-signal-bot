# CLAUDE.md — بوت إشارات تداول Binance

بوت توليد إشارات على Binance يعمل **Paper Trading فقط** (لا تداول حقيقي). الوضع الحالي: **التعلّم الحي** — يجمع صفقات حيّة بمؤشرات بسيطة + سياق ماكرو (BTC/ETH/USDT.D) ويتعلّم باستمرار من الدورة الحالية.

> اقرأ الملف المرتبط ذا الصلة قبل أي تعديل.

## أساسيات
- **المستخدم:** Basim | **الخادم الوحيد:** `89.58.35.49` (aarch64، 12 نواة، 23GB) | **التشغيل:** Docker Compose | **Python:** 3.12
- **PAPER_TRADING=true دائماً** — لا تغيّره.
- DB مباشرة: `docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "..."` (الدور `trading_signal_bot`، DB `trading_signals`).

## أوامر سريعة (قراءة فقط)
```bash
ops/compose-safe status                                                       # الحالة (مساعد قراءة فقط)
ops/compose-safe logs <service> --tail 30                                     # اللوقات (يحجب التوكنات)
research/skill_application/.venv/bin/python -m pytest tests/ -q               # اختبارات الوحدة
```

## سلامة التشغيل (Operations Safety) — إلزامي
المرجع الكامل: [docs/ops/COMPOSE_OPERATIONS.md](docs/ops/COMPOSE_OPERATIONS.md). يغلب أي أمر في وثيقة أخرى.
- **خادم واحد مشترك** (postgres المشترك + مشاريع أخرى): لا أوامر تطال "كل شيء"، و**خدمة واحدة في كل مرة**.
- **Class A (قراءة فقط، مسموح دائماً):** `docker ps` / `inspect` / `logs` / `stats --no-stream` / `image inspect`، و Compose `ps` / `logs` / `top` / `images`، و `config --hash <svc>` و `config --services`. **`docker compose config` العادي يطبع أسرار `.env` مفكوكة** — لا يُعرض على الطرفية أبداً؛ فقط إعادة توجيه لملف بصلاحية 600.
- **Class B (بموافقة صريحة من المالك + إجراء مُبوَّب):** restart/stop/recreate/deploy/rollback لخدمة **واحدة**، أو `exec` يكتب، أو تشغيل المتعلّم. الصيغة الوحيدة، من `/home/tradmin/trading-signal-bot` فقط:
  `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate <svc>`
  مع التقاط الهوية قبل/بعد (container ID، image، StartedAt، RestartCount، IPs)، وفحص صحة طازج ×2، وبوابتي PAPER_HALTED/B3.
- **Class C (ممنوع في الإنتاج):** `up`/`up -d` بلا خدمة، `up --build`، أي `build` من نسخة الإنتاج، `down`، `down -v`، `--remove-orphans`، أي `prune`، `pull` لصور التطبيق، `start`/`restart`/`rm` الشاملة، `run` يركّب مجلد الإنتاج، وأي تعديل لأكثر من خدمة.
- **المتعلّم (`continuous_learner`) يبقى متوقفاً:** في profile `learner`؛ تشغيله فقط بـ `--profile learner` وبتفويض منفصل من المالك. **الـprofile لا يجعل الأوامر العارية مقبولة.**
- **صور مثبّتة:** telegram و trade_tracker و scanner على صور `deploy/aiohttp-3.14.3/IMAGES.md` — لا إعادة بناء ولا إعادة وسم أبداً.
- **خدمات D3 محجوبة بالانجراف:** analyzer و signal_engine و claude_review — إعادة إنشائها تطبّق انجراف البيئة؛ ممنوعة قبل مرحلة D3.
- **مصدر الحقيقة:** `docker-compose.yml` في الإنتاج يجب أن يطابق الـblob المُراجَع في Git؛ أي تغيير عبر PR ثم تثبيت منفصل بتفويض مستقل مع تحقق `config --hash`.
- **قاعدة التوقف المطلقة:** أي شيء غير متوقع (hash مختلف، diff غير متوقع، تغيّر هوية حاوية، بوابة فاشلة، سرّ في المخرجات) = **توقّف وارجع للمالك**. لا تشخيص ثم متابعة.

## قواعد حرجة (تغلب الافتراضات)
- **العتبات الحيّة في DB (`optimizer_settings`/`indicator_weights`) تغلب `.env`** — راجع DB لا `.env`.
- **الشمعة المغلقة فقط** — لا look-ahead (الأنلايزر يُسقط الشمعة الجارية).
- `git add <paths>` محدّدة — **تجنّب `git add -A`** (مخرجات بحث ضخمة غير متعقّبة).

## التوثيق المفصّل
- [وضع التعلّم الحي (النظام الحالي)](docs/claude/live-learning.md)
- [البنية والقرارات التقنية](docs/claude/architecture.md)
- [قاعدة البيانات](docs/claude/database.md)
- [التشغيل والإعدادات + Telegram](docs/claude/operations.md)
- [المشاكل الشائعة وحلولها](docs/claude/troubleshooting.md)
- [تاريخ الاستراتيجية والأبحاث (لماذا تحوّلنا)](docs/claude/strategy-history.md)
- سجلّ التطوير: [DEV_LOG.md](DEV_LOG.md) | الإعداد: [SETUP_GUIDE.md](SETUP_GUIDE.md)
