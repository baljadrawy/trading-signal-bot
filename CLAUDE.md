# CLAUDE.md — بوت إشارات تداول Binance

بوت توليد إشارات على Binance يعمل **Paper Trading فقط** (لا تداول حقيقي). الوضع الحالي: **التعلّم الحي** — يجمع صفقات حيّة بمؤشرات بسيطة + سياق ماكرو (BTC/ETH/USDT.D) ويتعلّم باستمرار من الدورة الحالية.

> **مرجع إلزامي قبل كل مهمة:** اقرأ [OWNER_OPERATING_CONTRACT.md](docs/governance/OWNER_OPERATING_CONTRACT.md) ثم الوثائق المتخصصة. يضم قرارات المالك المعتمدة بتاريخ 2026-10-26: Continuous Development + PR-on-Demand، استمرارية Paper عند الخسائر الاقتصادية، Claude Code للتنفيذ، GitHub/runtime parity، وحدود النشر والسلامة. هذا لا يعني أن تعديل كود Paper أو نشره قد حدث. عند تعارض تعليمات سير العمل القديمة، قدّم قرار المالك الأحدث دون تجاوز قيود التشغيل/الأدلة/الحماية.

> اقرأ الملف المرتبط ذا الصلة قبل أي تعديل.

> **MASTER DIRECTION — OWNER APPROVED 2026-11-01 (MANDATORY BEFORE EVERY TASK):** Read [Trading System Master Charter](docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) in full before planning, coding, reviewing, proposing a strategy or drafting a Claude task. The current objective is active daily opportunity scanning (never forced daily trades), net-of-cost spot trading, strategy-specific holding and risk-controlled compounding of **realized net profits**. Preserve external-review and ERG-01 INCONCLUSIVE findings as evidence, not as an obsolete business objective. State WP0–WP5, R1–R9, baseline SHA, evidence class, permission gate and DEVIATION ALERT for every task. Never assume this charter authorizes protected research, production changes or deployment. Existing stricter operational and research governance remains binding. If a conflict arises, stop the affected action and ask the owner.


> **OWNER DECISION — WP2 INTEGRATED DEVELOPMENT (2026-11-01):** Before WP2 work, read [WP2 Integrated Development Decision](docs/governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md). Develop and integrate directly in the existing bot source, not a separate replacement or dormant-only library. Source integration and isolated disposable dev-container tests are authorized; shared-host/live Paper service operations still require the specific COMPOSE_OPERATIONS.md gate. Preserve research freezes, PAPER_ONLY, A29 HOLD and version-boundary approval. Report implemented/integrated/tested/deployed separately.

> **OWNER DECISION — FUNCTIONAL INCREMENTAL PAPER ACTIVATION (2026-11-01):** Before WP2 work, read [Functional Incremental Paper Activation](docs/governance/WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md). Deliver coherent increments: Scanner/Analyzer/Signal Engine → integrity/delivery → tracker/economics → portfolio/risk → evaluation. Baseline → implement → test → independent review → specific owner-authorized Paper activation → observe → accept/fix/rollback. This method approval does not authorize shared-host Class B actions or protected research.

## Development-First policy (owner workflow directive effective 2026-10-26)

- [docs/governance/DEVELOPMENT_FIRST_POLICY.md](docs/governance/DEVELOPMENT_FIRST_POLICY.md): which rules apply to which kind of work (D0 development … D5 live). Development is the default; production operations, the sealed holdout, secrets and PAPER_ONLY rules are unchanged. Owner's dated 2026-10-26 workflow directive is effective; older proposed text is historical and does not override production safety.

## R1.3 recovery governance (merged in PR #46, 2026-10-18)

- Bot-owned backups are **per approved container update**, not periodically; preserve the prior certified recovery set until the replacement passes verification and a separate, named deletion is approved.
- Use `ops/provenance/drift_check.py` as a **development and deployment governance gate**, not a scheduled independent service. Report the executed verification scope and never treat `main` HEAD as the deployed image.
- Read [docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md](docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md). This documentation change **does not** authorize cron, backup, DB, container, or deletion operations.

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
  مع التقاط الهوية قبل/بعد (container ID، image، StartedAt، RestartCount، IPs)، وفحص صحة طازج ×2، وبوابتي PAPER_HALTED/B3 (حالة الإيقاف **غير مؤكَّدة** من DB منذ R0؛ يُتحقَّق منها من DB قبل أي خطوة، راجع `docs/ops/COMPOSE_OPERATIONS.md`). *ملاحظة 2026-10-20:* قاطع B3 يُحسب من الصفقات المغلقة عند كل تقييم وليس قيمة مخزّنة، فلا يُذكر PAPER_HALTED كحالة حالية دون قراءة معتمدة.
- **Class C (ممنوع في الإنتاج):** `up`/`up -d` بلا خدمة، `up --build`، أي `build` من نسخة الإنتاج، `down`، `down -v`، `--remove-orphans`، أي `prune`، `pull` لصور التطبيق، `start`/`restart`/`rm` الشاملة، `run` يركّب مجلد الإنتاج، وأي تعديل لأكثر من خدمة.
- **المتعلّم (`continuous_learner`) يبقى متوقفاً:** الـprofile `learner` يمنعه فقط من المشاركة في التشغيل الافتراضي العادي لـCompose (حماية من التشغيل العرضي). استهداف المتعلّم مباشرةً بالاسم يبقى ممكناً تقنياً في Docker Compose، و**ممنوع** دون تفويض منفصل من المالك. **الـprofile ليس حدّ تفويض:** حدّ التفويض هو موافقة المالك الصريحة + إجراء Class B + هذا المرجع + رفض `ops/compose-safe` للمتعلّم + قاعدة التوقف المطلقة. لا تستهدف `continuous_learner` بأي أمر Compose؛ أي تشغيل مقصود يتم فقط عبر الإجراء المُراجَع وبتفويض منفصل. **الـprofile لا يجعل الأوامر العارية مقبولة.**
- **صور مثبّتة:** المرجع الحالي هو `deploy/DEPLOYED.json` (مطابَق مع الحاويات الجارية 2026-10-27): analyzer و signal_engine على صور الإصدار `tsb-a561-*:rel-ea8ae4f-r2` (`deploy/a561-rel-ea8ae4f/IMAGES.md`)، و telegram و trade_tracker على `tsb-obs-*:bb7825f-20261027-r2` بوضع `PAPER_ECONOMIC_HALT_MODE=observe` (`deploy/paper-observe-bb7825f/IMAGES.md`، حدّ النسخة في `deploy/VERSION_BOUNDARY.md`؛ صور التراجع `tsb-a561-*:rel-ea8ae4f-r2`)، و scanner على صورة `deploy/aiohttp-3.14.3/IMAGES.md`. سجلّات D3B-1/CR-2/P1-D تاريخية (صور التراجع `tsb-p1d-*`). لا إعادة بناء ولا إعادة وسم أبداً.
- **claude_review مُتقاعد من التشغيل (CR-2):** ليس خدمة في `docker-compose.yml`؛ المسار النشط signal_engine → `signal.ready` → telegram → trade_tracker. صورها والمصدر والبيانات التاريخية محفوظة للتراجع (`deploy/cr2-signal-ready/RETIREMENT.md`). **مرصود 2026-10-18 (R0):** الحاوية المتوقفة `trading_claude_review` لم تعد موجودة، والباقي صورها فقط، فالتراجع عن CR-2 يتطلّب إنشاءً من الصورة. أي حذف بتفويض منفصل فقط.
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
