# Permission Matrix — RBAC

**Дата ревизии:** 2026-05-14
**Источники:** [user_role.py](../../../reddit_saas/app/models/user_role.py), [rbac-client-isolation/requirements.md](requirements.md), [client-manager-workflow-ux/requirements.md](../client-manager-workflow-ux/requirements.md)

Документ покрывает Requirement 11 из `rbac-client-isolation/requirements.md` (Permission Matrix Documentation).

## 1. Роли и кто это

| Роль | Кто | Скоуп | Уровень доступа |
|---|---|---|---|
| 👑 **owner** | Max | вся платформа | полный, включая kill-switches, инфра |
| 🤝 **partner** | Tzvi, Jenny | все клиенты | бизнес-админ, но НЕТ доступа к system settings / kill-switches |
| 🔍 **qa** | Jenny (cross-review) | все клиенты, read-only + свой аватар-фарм | review/approve/reject для всех, can warm own avatars |
| 🏢 **client_admin** | админ B2B-компании | только своя `client_id` | team + avatars + drafts + client settings |
| 👤 **client_manager** | B2B-контакт клиента | только своя `client_id` | approve/reject + subreddits/keywords, **не** аватары, **не** users |
| 👁️ **client_viewer** | B2B read-only | только своя `client_id` | dashboard + reports (read), approve только если `draft_approval_enabled` |
| 🎯 **b2c_user** | self-service | 1 свой аватар | упрощённый UI, лимит 1 аватар |

## 2. Матрица «ресурс × роль»

Легенда: ✅ allow · ❌ deny · 🔒 scoped (только своя `client_id`) · 👁️ read-only

| Ресурс / действие | owner | partner | qa | client_admin | client_manager | client_viewer | b2c_user |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **System settings / kill switches** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Admin panel `/admin/*`** | ✅ | ✅ | ✅ (read) | ❌ | ❌ | ❌ | ❌ |
| **Создать/изменить Client** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Просмотр Client** | all | all | all 👁️ | 🔒 own | 🔒 own | 🔒 own 👁️ | 🔒 own |
| **Client settings (brand, plan)** | ✅ | ✅ | ❌ | 🔒 own | ❌ | ❌ | ❌ |
| **Создать аватар (owned)** | ✅ | ✅ | ❌ | 🔒 own, до `max_avatars` | ❌ | ❌ | ❌ (только 1, при регистрации) |
| **Удалить аватар** | ✅ | ✅ | ❌ | 🔒 own | ❌ | ❌ | ❌ |
| **Назначить/настроить аватар** | ✅ | ✅ | ❌ | 🔒 own | ❌ | ❌ | 🔒 свой |
| **Warm own avatar (farm)** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Rent farm avatar** | ✅ | ✅ | — | 🔒 own | ❌ | ❌ | ❌ |
| **Subreddits / keywords** | ✅ | ✅ | 👁️ | 🔒 own | 🔒 own | 🔒 own 👁️ | 🔒 own |
| **Approve / reject draft** | ✅ | ✅ | ✅ all | 🔒 own | 🔒 own | 🔒 only if `draft_approval_enabled` | 🔒 own |
| **Edit draft** | ✅ | ✅ | ✅ | 🔒 own | 🔒 own | 🔒 if flag | 🔒 own |
| **Batch approve/reject** | ✅ | ✅ | ✅ | 🔒 own | 🔒 own | ❌ | ❌ |
| **Trigger pipeline (scrape/score/generate)** | ✅ | ✅ | ❌ | ❌* | ❌ | ❌ | ❌ |
| **Создать user** | ✅ любая роль | ✅ любая роль | ❌ | 🔒 только client_manager / client_viewer внутри своей компании | ❌ | ❌ | ❌ |
| **Deactivate user** | ✅ | ✅ | ❌ | 🔒 own team | ❌ | ❌ | ❌ |
| **AI cost analytics / audit logs** | ✅ all | ✅ all | 👁️ | ❌ | ❌ | ❌ | ❌ |
| **Activity feed / reports** | ✅ all | ✅ all | 👁️ all | 🔒 own | 🔒 own | 🔒 own 👁️ | 🔒 own |

\* По текущему enum `can_trigger_pipeline = {owner, partner}` — client_admin триггер пайплайна делать **не может**, см. [user_role.py:77-79](../../../reddit_saas/app/models/user_role.py#L77-L79).

## 3. Workflow по ролям

### 👑 owner (Max)
1. Заводит partner-ов и client_admin-ов.
2. Включает/выключает kill-switches, меняет system settings (rate limits, scrape window).
3. Смотрит платформенные метрики, AI costs, audit log.
4. Доступ ко всему без скоупа.

### 🤝 partner (Tzvi)
1. Онбоардинг клиента: создаёт Client → задаёт `max_avatars`, `plan_type`, `draft_approval_enabled`.
2. Создаёт `client_admin` и линкует к Client (или сам управляет от его имени).
3. Запускает пайплайны (scrape/score/generate) для любого клиента.
4. Смотрит cross-client отчёты, AI costs, audit log.
5. Не лезет в system settings / kill-switches.

### 🔍 qa (Jenny)
1. Каждый день: открывает Review Queue → approve/reject/edit драфты **по всем клиентам**.
2. Параллельно: warm-up своих личных аватаров на farm.
3. Read-only по threads, activity, reports — для контекста при review.

### 🏢 client_admin (админ B2B)
1. Регистрируется (или его создаёт partner) → видит только свой `client_id`.
2. Заводит команду: `client_manager` и `client_viewer` внутри своей компании.
3. Создаёт/удаляет/настраивает свои аватары (в пределах `max_avatars`).
4. Может арендовать аватара из farm.
5. Approve/reject драфты, настройки клиента (brand, voice).
6. **Не** триггерит пайплайн, **не** видит system settings, **не** видит чужих клиентов.

### 👤 client_manager (B2B-контакт)
1. Логинится → видит только свой `client_id`.
2. Daily: Review Queue → approve/reject/edit драфты своей компании.
3. Добавляет subreddits / keywords / правки таргетинга.
4. **Не** управляет аватарами (только использует) и **не** управляет пользователями.

### 👁️ client_viewer
1. Read-only dashboard + reports + activity своей компании.
2. Approve/reject — **только** если у Client включён `draft_approval_enabled`.
3. Никаких изменений в настройках, subreddits, аватарах.

### 🎯 b2c_user
1. Self-service: один свой аватар.
2. Видит/редактирует только своё.
3. Попытка создать 2-й аватар → 403 "B2C users can have only one avatar".
4. При апгрейде до B2B — конвертация в первый аватар компании.

## 4. Что управляется отдельно (объекты)

| Объект | Создаёт | Удаляет | Настраивает | Использует/approve |
|---|---|---|---|---|
| **Client** | owner, partner | owner, partner | owner, partner; client_admin (своего, частично) | все scoped роли — внутри своего |
| **Avatar (owned)** | owner, partner, client_admin | owner, partner, client_admin | те же | + client_manager, client_viewer (только select при approve) |
| **Avatar (farm/rent)** | owner, partner (создание farm); client_admin (rental) | owner, partner | — | владелец аренды |
| **Subreddit assignment** | owner, partner, client_admin, client_manager | те же | те же | viewer 👁️ |
| **CommentDraft / PostDraft** | пайплайн | пайплайн | edit: owner, partner, qa, client_admin, client_manager (+viewer if flag) | approve/reject — те же |
| **User** | owner, partner (любая роль); client_admin (mgr/viewer своей компании) | те же | те же | — |
| **System settings / kill switches** | owner | owner | owner | — |

## 5. Известные дыры (фактическое состояние vs. спека)

- `client_admin` **отсутствует** в селекте формы создания юзера ([admin_users.html:56-66](../../../reddit_saas/app/templates/admin_users.html#L56-L66)) — нельзя завести через UI, только через БД.
- Бейдж для `client_admin` не отрисовывается ([admin_user_row.html:14-28](../../../reddit_saas/app/templates/partials/admin_user_row.html#L14-L28)).
- `can_trigger_pipeline` в коде включает только owner/partner ([user_role.py:77-79](../../../reddit_saas/app/models/user_role.py#L77-L79)); спека намекает, что client_admin может триггерить из Client Hub — это надо согласовать (либо расширить permission, либо явно скрыть кнопки).
- `client_viewer` approve flow зависит от флага `Client.draft_approval_enabled` — флаг описан в [requirements.md](requirements.md), но в Permission_Guard в коде сейчас не разрулен.

## Changelog

| Дата | Изменение |
|---|---|
| 2026-05-14 | Первая версия документа: матрица + workflow + дыры |
