# Status Report — May 1, 2026 (Day 1)

## Partnership

- **Формат:** 50/50 partnership
- **Max Breger:** Tech (вся разработка)
- **Tzvi Vaknin:** Business (клиенты, маркетинг, ревью контента)
- **Юрлицо:** Кипрская компания (Tzvi CEO, EU citizenship)
- **Финансирование:** Prepaid pilot client (~$4K setup + ~$2K/мес)

---

## Что сделано сегодня (Day 1)

### Анализ
- ✅ Изучен весь пакет документов от Ori (25+ файлов)
- ✅ Проанализированы все 9 n8n workflows, промпты, стратегия
- ✅ Изучен конкурент ReddGrow (pricing, features, архитектура)
- ✅ Изучен LinkedIn пост основателя ReddGrow (внутренняя архитектура)

### Документация
- ✅ `memory.md` — ключевая информация по проекту
- ✅ `session.md` — лог сессий
- ✅ `decisions.md` — решения и открытые вопросы
- ✅ `file_index.md` — индекс всех файлов с пояснениями
- ✅ `letter_to_tzvi.md` — письмо Цви с анализом и планом
- ✅ `call_notes_tzvi.md` — легенда на звонок
- ✅ `ai_cost_benchmark.md` — расчёт стоимости AI на клиента

### Разработка (начато)
- ✅ Инициализирован проект `reddit_saas/`
- ✅ pyproject.toml с зависимостями
- ✅ Конфигурация (pydantic-settings)
- ✅ Database setup (SQLAlchemy + PostgreSQL)
- ✅ Начаты модели: User, Client (остальные в процессе)

### Ключевые решения
- ✅ Строим SaaS с нуля (не используем n8n/Airtable)
- ✅ Стек: FastAPI + Jinja2/HTMX + PostgreSQL + Celery + Redis + PRAW + LiteLLM
- ✅ От Ori берём только промпты, стратегию, voice profiles, keywords
- ✅ AI cost: ~$36/мес на клиента при стандартном объёме

---

## Что ждём

| От кого | Что | Статус |
|---------|-----|--------|
| Tzvi | Задание на первого клиента (brief) | ⏳ Ждём |
| Tzvi | Functional requirements (UI/UX) | ⏳ Ждём |
| Tzvi | Exact AI token costs от Ori | ⏳ Ждём |
| Tzvi | Reddit API credentials | ⏳ Ждём |
| Tzvi | Pricing model + pilot onboarding strategy | ⏳ Ждём |
Стандартный объём = как работал Ori: 15 профессиональных комментариев + 15 hobby + 2 поста в день.

Разбивка:

Что	Кол-во/день	Модель	Стоимость/день
Скоринг 200 постов	200	Gemini Flash ($0.075/1M)	$0.06
Выбор персоны для 15 постов	15	Claude Sonnet ($3/1M)	$0.23
Генерация 15 комментариев	15	Claude Sonnet ($3/1M)	$0.54
Редактор качества 15 комментариев	15	Claude Sonnet ($3/1M)	$0.23
15 hobby комментариев	15	Gemini Flash	$0.03
2 поста	2	Claude Sonnet	$0.10
Итого в день			$1.19
$1.19 × 30 дней = ~$36/мес

Это из ai_cost_benchmark.md — расчёт по реальным размерам промптов Ori которые я вытащил из его workflow JSON файлов.
---

## Roadmap

### Phase 1 — MVP (~80-100 часов)

**Этап 1A: Core Pipeline (недели 1-3)**

| Неделя | Блок | Часы | Статус |
|--------|------|------|--------|
| 1 | Архитектура + БД + Auth + Docker | 12-15 | 🔄 Начато |
| 1-2 | Reddit API интеграция (PRAW) | 10-12 | ⬜ |
| 2 | AI pipeline (scoring + persona + generation) | 15-18 | ⬜ |
| 2-3 | Review UI (Jinja2 + HTMX) | 10-12 | ⬜ |

**Результат 1A:** Работающий pipeline: Reddit → AI → Review UI. Первый клиент может начать работать.

**Этап 1B: Polish + Reliability (недели 3-5)**

| Неделя | Блок | Часы | Статус |
|--------|------|------|--------|
| 3-4 | Persona system + hobby karma pipeline | 10-12 | ⬜ |
| 4 | Celery jobs + scheduling + reliability | 8-10 | ⬜ |
| 4-5 | Tracking + basic analytics | 6-8 | ⬜ |
| 5 | Prompt tuning на реальных данных | 8-10 | ⬜ |

**Результат 1B:** Production-ready MVP для первого клиента.

### Phase 2 — Multi-tenant + 2 клиента (недели 6-8)

- Client onboarding через UI
- Настройка аватаров/сабреддитов через интерфейс
- Subreddit auto-suggest
- Shadowban detection
- Подключение 2 новых клиентов

### Phase 3 — SaaS features (ongoing)

- Аналитика (karma, engagement, ROI)
- Slack интеграция
- Content repurposing
- Semi-automated posting
- Knowledge lake
- Billing

---

## Бюджет инфраструктуры

| Статья | В месяц |
|--------|---------|
| VPS (4 CPU, 8GB RAM) | $30-40 |
| AI / LLM API (на клиента) | $25-60 |
| Домен + SSL | ~$1 |
| **Итого (1 клиент)** | **~$55-100** |
| **Итого (5 клиентов)** | **~$200-350** |

При $2K/мес с клиента → маржа ~95%.

---

## Риски

| Риск | Вероятность | Митигация |
|------|------------|-----------|
| Reddit бан аватаров | Средняя | Human-in-the-loop, hobby karma, invite-only |
| Reddit API ограничения | Низкая | Script-type app для чтения бесплатный |
| AI hallucinations | Средняя | Editor prompt + human review |
| Цви не приведёт клиента | Средняя | MVP делаем параллельно, не ждём |
| Prompt quality ниже Ori | Средняя | Берём промпты Ori как baseline, тюним |

---

*Next update: после получения brief от Tzvi на первого клиента.*
