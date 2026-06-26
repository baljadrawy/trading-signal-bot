# CLAUDE.md — بوت إشارات تداول Binance

بوت توليد إشارات على Binance يعمل **Paper Trading فقط** (لا تداول حقيقي). الوضع الحالي: **التعلّم الحي** — يجمع صفقات حيّة بمؤشرات بسيطة + سياق ماكرو (BTC/ETH/USDT.D) ويتعلّم باستمرار من الدورة الحالية.

> اقرأ الملف المرتبط ذا الصلة قبل أي تعديل.

## أساسيات
- **المستخدم:** Basim | **الخادم الوحيد:** `89.58.35.49` (aarch64، 12 نواة، 23GB) | **التشغيل:** Docker Compose | **Python:** 3.12
- **PAPER_TRADING=true دائماً** — لا تغيّره.
- DB مباشرة: `docker exec -i postgres psql -U trading_signal_bot -d trading_signals -c "..."` (الدور `trading_signal_bot`، DB `trading_signals`).

## أوامر سريعة
```bash
docker compose build --no-cache <service> && docker compose up -d <service>   # بعد تغيير الكود
docker compose ps                                                             # الحالة
docker compose logs <service> --tail=30 -f                                    # اللوقات
research/skill_application/.venv/bin/python -m pytest tests/ -q               # اختبارات الوحدة
```

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
