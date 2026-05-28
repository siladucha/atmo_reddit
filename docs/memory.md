# Memory — Reddit Marketing SaaS

> ⚠️ **This file is legacy.** The canonical knowledge base is now at [`docs/kb/`](./kb/README.md).  
> This file is kept for historical reference. New documentation goes into `docs/kb/`.

## Partnership
- **50/50** — Tzvi (бизнес/маркетинг/клиенты) + Max (вся разработка)
- **Юрлицо:** Кипрская компания, Tzvi CEO (EU citizenship)
- **Финансирование:** Prepaid pilot client (~$4K setup + ~$2K/мес) → фонд на MVP

## Product
- Reddit marketing SaaS для B2B компаний
- AI мониторит сабреддиты, скорит посты, генерирует комментарии от лица аватаров
- **Human-in-the-loop:** Tzvi — gatekeeper, одобряет/редактирует весь контент
- Avatar pre-warming (hobby karma) для готовности аккаунтов к работе
- Invite-only модель для снижения рисков

## Tech Stack
- **Backend:** Python + FastAPI
- **UI:** Jinja2 + HTMX
- **DB:** PostgreSQL + SQLAlchemy + Alembic
- **Auth:** FastAPI + JWT
- **Jobs:** Celery + Redis
- **Reddit:** PRAW
- **AI/LLM:** LiteLLM (OpenRouter/Claude/Gemini)
- **Deploy:** Docker + VPS → AWS позже

## MVP Scope (~100 часов)
- Повторить логику PoC Ori как нормальный код
- Reddit API → скоринг → persona routing → генерация комментариев → review UI
- Multi-tenant архитектура заложена с самого начала
- Hobby karma pipeline
- Cost-efficient AI architecture

## Сделано на 2026-05-03
- Auth middleware (JWT cookie, защита всех роутов)
- Error handling middleware (HTML страницы ошибок)
- Celery Beat scheduler с 4 задачами (8:00, 14:00, 10:00, каждые 12ч)
- Orchestrator tasks — пакетный прогон по всем clients/avatars
- Avatar health checks (shadowban + karma)
- 12 шаблонов Jinja2 + HTMX + Tailwind
- 60 unit-тестов (9 модулей) — проходят
- Avatar creation, user guide, daily log rotation
- Документация в `docs/`

## Сделано на 2026-05-11
- Client deactivation cascade: is_active=false → subreddit assignments off → avatars unassigned → all pipeline tasks skip
- Guard checks `client.is_active` in every per-client task (score_threads, generate_comments, generate_posts, scrape_professional_subreddits)
- Shared subreddit registry: queue_tick only scrapes subs with at least one active client assignment

## Конкуренты
- **ReddGrow** ($59-299/мес) — self-service, mass market, AI visibility tracking
- **Мы** ($2K+/мес) — premium managed service, глубокие персоны, стратегия

## Риски
- Reddit бан аккаунтов/доменов → invite-only + client liability disclaimers
- AI token costs → benchmark по PoC Ori, cost controls в архитектуре
- Reddit API доступ → проверить script-type app, готовить альтернативу

## Из PoC Ori берём
- Промпты и стратегию комментирования
- Структуру персон/аватаров (voice profiles)
- Логику скоринга (relevance/quality/strategic)
- Стратегию fallback (Paradigm Shift → Helpful → Karma)
- Keywords и категории
- Схему БД (адаптируем)

## Клиент
- Первый клиент: через Tzvi (pilot, prepaid)
- Предыдущий клиент Ori: XM Cyber (кибербезопасность)
- NDA — прямого доступа к клиентам нет, всё через Tzvi
