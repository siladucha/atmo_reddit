# Q&A Session — May 15, 2026

## Контекст

Сессия вопросов-ответов по текущему состоянию платформы RAMP (Reddit Avatar Marketing Platform).
Цель: понять что блокирует запуск, что работает, что нет, и приоритеты.

---

## 1. 🎯 Что блокирует запуск первого клиента?

### 🔴 Блокеры (без них клиент не может работать)

| # | Что | Почему блокирует | Статус |
|---|-----|-----------------|--------|
| 1 | **Telegram Bot** | Без него нет "last mile" — одобренные комментарии некому постить. Copy-paste из админки не масштабируется даже на 1 клиента с 5 аватарами. | Spec ready, код не начат |
| 2 | **Production Deploy** | Система работает только на localhost. Цви/клиент/avatar owners не могут зайти. | Docker ready, сервер DigitalOcean есть, нужен rsync + docker compose up |
| 3 | **XM Cyber Data Validation** | Первый клиент — XM Cyber. Нужно убедиться что их subreddits/keywords/personas загружены и pipeline генерирует адекватные комментарии. Без этого — запуск вслепую. | Не начато |

### 🟡 Важно, но не блокирует запуск

| # | Что | Почему не блокирует |
|---|-----|-------------------|
| 4 | **Fleet Dashboard** | Можно управлять через текущий `/admin/avatars` — неудобно, но работает. Для 1 клиента с 5-7 аватарами — терпимо. |
| 5 | **Ждём Цви** | Нет. Техническая часть — на нас. Цви нужен для: подписание контракта с XM Cyber, передача avatar accounts, координация с avatar owners. |

### Рекомендованный порядок действий

```
1. Production Deploy        — 2-3 часа (rsync + compose up + проверка)
2. XM Cyber validation      — 1 день (загрузка данных + тестовый прогон pipeline)
3. Telegram Bot             — 2-3 дня (aiogram + webhook + avatar_assignments)
```

---

## 2. 📈 Готовность к масштабу

| Вопрос | Ответ | Сложность | Когда нужно |
|--------|-------|-----------|-------------|
| **Pagination на всех списках** | Не внедрена. | S (1-2 дня) | До 10 клиентов |
| **Idempotency keys** | Не внедрены. Celery retry может создать дубли (теоретически). | M (2-3 дня) | До 10 клиентов |
| **Бюджетный движок (лимиты на аватара)** | Не внедрён. Логика: `daily_limit = monthly_cap / 30`, проверка перед `generate_comment`. Нужна таблица `avatar_budget`. | M (2-3 дня) | До 10 клиентов |
| **Cross-avatar deduplication** | Не внедрена. Проверка: `SELECT 1 FROM comment_drafts WHERE thread_id = X AND avatar_id != current AND status != 'rejected'`. | S (1 день) | P1 — палево если два аватара одного клиента отвечают в один тред |

### Приоритет для масштаба

1. **Deduplication** (P1) — палево, два аватара в одном треде
2. **Budget engine** (P1) — перерасход без лимитов
3. **Pagination** (P1) — UX ломается на больших списках
4. **Idempotency** (P2) — edge case, низкий риск при текущей нагрузке

---

## 3. 🎨 Avatar Detail — текущее состояние UI

| Вопрос | Ответ |
|--------|-------|
| **12 вкладок → сколько осталось?** | Сейчас на странице аватара: Overview, Performance, Presence, Learning, Health, Strategy + HTMX-подгружаемые панели (confidence, removal, patterns, learned patterns, presence). Это не 12 отдельных страниц — это табы на одной странице. |
| **Единый экран аватара** | Можно сделать: убрать табы → вертикальный scroll с секциями. 1 день работы. Вопрос: нужен "всё на одном экране" или "самое важное наверху, остальное ниже"? |
| **Воронка (scrape→generate→review→post)** | Не визуализирована как pipeline для конкретного аватара. Есть Activity Feed (список событий) и Topology (системный граф). Для аватара — нет визуальной воронки "сколько тредов → сколько комментов → сколько одобрено → сколько опубликовано". Это задача Fleet Dashboard. |
| **Свежесть данных** | Частично: `last_scraped_at` на subreddits, stale indicators на presence (🟢🟡🔴). На самой странице аватара — нет общего "data freshness" индикатора. |

---

## 4. 🧠 Self-learning — статус и как проверить

| Вопрос | Ответ |
|--------|-------|
| **Edit record сохраняется?** | ✅ Да. Хук `capture_edit_record` вызывается при approve/reject/edit в обоих routes (API + UI HTMX). Проверить: `/admin/avatars/{id}` → Learning tab → видны записи. Или в БД: `SELECT count(*) FROM edit_records WHERE avatar_id = X`. |
| **Коррекция паттернов — когда запускается?** | ✅ `recompute_correction_patterns` запускается автоматически каждые 5 новых edit records для аватара. Извлекает до 6 типов паттернов, хранит max 3 активных на тип. |
| **Few-shot примеры — инжектятся в промпт?** | ✅ Да. `format_learning_context()` вызывается в `generate_comment()` — инжектит между voice profile и thread context. `learning_metadata` JSONB на draft хранит что было инжектировано. |
| **Apostolate (1.55M karma) — используется как ментор?** | Если `warming_phase = 0` — да, это Mentor. Исключён из всех автоматических пайплайнов. Используется только для "reputation presence". Его стиль НЕ копируется автоматически на других аватаров. |
| **Как посмотреть, чему научился аватар?** | `/admin/avatars/{id}` → Overview tab → "Learned Patterns" панель. Показывает active `CorrectionPattern` записи: тип, правило, частота, last_seen. Также Performance tab → "What Works / What Fails". |

---

## 5. 🩺 Health Score — формула

### Текущая реализация: Confidence Score (не Health Score)

В системе реализован **Confidence Score** (0-100), а не "Health Score". Это разные вещи:

- **Confidence Score** = насколько мы уверены в качестве контента аватара
- **Health Score** (не реализован) = общее здоровье аккаунта (CQS + shadowban + activity)

### Формула Confidence Score

```
Base:              50 points (всегда)
+ Karma bonus:    до +30 (avg_karma >= 3 per comment = full bonus)
- Removal penalty: до -30 (removal_rate >= 30% = full penalty)
+ Diversity bonus: до +20 (5+ unique subreddits = full bonus)
= Score:          0-100
```

### Компоненты

| Компонент | Источник данных | Вес |
|-----------|----------------|-----|
| Средняя карма на комментарий | `AvatarSubredditPresence` (total_karma / comment_count) | +30 max |
| Removal rate | `CommentDraft` (is_deleted=True среди posted) | -30 max |
| Разнообразие сабреддитов | Количество уникальных сабреддитов в presence | +20 max |

### Почему Flaky_Finder_13 = 34, а Hot-Thought2408 = 92?

| Метрика | Flaky_Finder_13 | Hot-Thought2408 |
|---------|-----------------|-----------------|
| Avg karma | Низкая (<1) → karma_bonus ≈ 0-10 | Высокая (3+) → karma_bonus = 30 |
| Removal rate | Высокая (>20%) → penalty = 20-30 | Низкая (<5%) → penalty ≈ 5 |
| Unique subs | Мало (1-2) → diversity = 4-8 | Много (4+) → diversity = 16-20 |
| **Итого** | 50 + 5 - 25 + 4 = **34** | 50 + 30 - 5 + 17 = **92** |

### Где отображается

- `/admin/avatars/{id}` → Overview tab → Confidence Score панель (HTMX lazy-load)
- Endpoint: `GET /admin/avatars/{id}/confidence`

### История изменения

❌ **Не реализована.** Confidence Score вычисляется на лету при каждом запросе. Нет таблицы с историческими снимками. Для истории нужна таблица `confidence_snapshots` + Celery Beat задача (ежедневный снимок).

---

## 6. 🎯 Приоритеты — что делаем в первую очередь

### Для запуска первого клиента (P0)

| # | Задача | Время | Блокирует |
|---|--------|-------|-----------|
| 1 | Production Deploy | 2-3 часа | Всё |
| 2 | XM Cyber data validation | 1 день | Качество |
| 3 | Telegram Bot | 2-3 дня | Posting |

### Для управления 15 аватарами за 10 минут в день (P1)

| # | Задача | Время |
|---|--------|-------|
| 1 | Fleet Dashboard (таблица всех аватаров с ключевыми метриками) | 2-3 дня |
| 2 | Avatar Detail (один scroll вместо табов) | 1 день |
| 3 | Цветовая кодировка проблем (🔴🟡🟢 на всех метриках) | 1 день |
| 4 | Batch operations (freeze всех неактивных за 1 клик) | 1 день |

### Для масштаба до 10 клиентов (P1-P2)

| # | Задача | Время |
|---|--------|-------|
| 1 | Cross-avatar deduplication | 1 день |
| 2 | Budget engine | 2-3 дня |
| 3 | Pagination | 1-2 дня |
| 4 | Авто-обновление CQS (уже сделано — Celery Beat 06:30) | ✅ Done |
| 5 | Уведомления о проблемах (Telegram alert channel) | 1-2 дня |

---

## 7. Дополнительные вопросы из сессии

### Архитектура и данные

| Вопрос | Ответ |
|--------|-------|
| Как измеряем здоровье аватара? | Confidence Score (0-100) — реализован. Полноценный Health Score (CQS + shadowban + activity + age) — не реализован как единая метрика. |
| Можно ли посмотреть историю Health Score? | ❌ Нет. Нужна таблица снимков + ежедневная задача. |

### Свежесть данных

| Вопрос | Ответ |
|--------|-------|
| Почему CQS нужно обновлять вручную? | ❌ Неверно — CQS обновляется автоматически (Celery Beat, ежедневно 06:30). Ручное обновление — дополнительная опция в UI. |
| Почему shadowban check — manual? | ❌ Неверно — shadowban check автоматический (Celery Beat, 07:30 и 13:30). Ручной — дополнительная кнопка. |
| Как пользователь узнает, что данные устарели? | Stale indicators на presence (🟢🟡🔴). На других панелях — нет индикатора свежести. |

### Управление 15 аватарами

| Вопрос | Ответ |
|--------|-------|
| Как быстро найти аватар с упавшим CQS? | Сейчас: `/admin/avatars` → ищи глазами. Нужно: Fleet Dashboard с сортировкой по CQS + цветовой кодировкой. |
| Как узнать, кто не публиковал >7 дней? | Сейчас: нет такого фильтра. Нужно: колонка "Last Posted" в Fleet Dashboard + фильтр "inactive >7d". |
| Можно ли заморозить всех неактивных за 1 клик? | ❌ Нет. Нужно: batch operations (checkbox + "Freeze Selected"). |
| Есть ли уведомления о проблемах? | ❌ Нет. Нужно: Telegram alert channel (shadowban detected, CQS dropped, avatar frozen). |

### AI и обучение

| Вопрос | Ответ |
|--------|-------|
| Я отредактировал комментарий → система запомнила? | ✅ Да. `capture_edit_record` сохраняет diff. После 5 правок — извлекает паттерны. |
| Можно ли скопировать стиль с одного аватара на другой? | ❌ Нет. Каждый аватар учится отдельно. Теоретически можно скопировать `correction_patterns`, но это не реализовано. |

### Безопасность

| Вопрос | Ответ |
|--------|-------|
| CQS = LOWEST → что делает система? | ✅ Автоматически замораживает аватар (Phase 2+). Phase 1 — не замораживает (даёт прогреться). |
| Если Reddit забанит аватар — как узнаем? | ✅ Health check (2 раза в день) детектит shadowban/suspension. Auto-freeze при обнаружении. |
| Есть ли автоматический freeze при shadowban? | ✅ Да. `health_checker.py` → auto-freeze + audit log. |
| Кто может заморозить/разморозить аватар? | Owner, Partner (через admin panel). Client_admin — нет (только просмотр своих аватаров). |

### Бизнес и деньги

| Вопрос | Ответ |
|--------|-------|
| $0.57 за 54 AI calls — нормально? | ✅ Да. ~$0.01 per call. При 15 аватарах × 15 комментов/день = ~$1.17/день/клиент = ~$35/мес. При подписке $399+ — маржа 91%+. |
| Какой budget на 15 аватаров в месяц? | ~$35/мес AI costs (при текущих ценах Gemini Flash + Claude Sonnet). AWS infra: ~$27/мес. Итого: ~$62/мес на 1 клиента. |
| При скольких клиентах система profitable? | При 1 клиенте на Starter ($399/мес): revenue $399 - costs $62 = profit $337/мес. Profitable с первого клиента. |
| Как передаём AI costs клиенту? | Включены в подписку. Клиент не видит AI costs отдельно. Plan limits (max comments/month) контролируют расход. |

---

## 8. Итоговая картина

### Что работает хорошо ✅

- Pipeline (scrape → score → generate → review) — полностью функционален
- Self-learning loop — сохраняет правки, извлекает паттерны, инжектит few-shot
- Safety (freeze, kill switches, shadowban detection, CQS monitoring)
- RBAC (6 ролей, изоляция данных, permission guards)
- AI costs — прозрачны, маржинальность 90%+
- Approach diversity — karma-aware ротация стилей

### Что сломано или недоделано ❌

- Нет production deploy (localhost only)
- Нет Telegram bot (last mile posting)
- Нет Fleet Dashboard (нельзя видеть 15 аватаров одним взглядом)
- Нет единого Health Score (только Confidence Score)
- Нет истории метрик (snapshots)
- Нет уведомлений о проблемах
- Нет batch operations
- Нет cross-avatar deduplication
- Нет budget engine

### Финальный ответ: что нужно для "10 минут в день на 15 аватаров"

```
Fleet Dashboard (таблица с сортировкой/фильтрами)
+ Цветовая кодировка (🔴🟡🟢 на каждой метрике)
+ Batch operations (freeze/unfreeze selected)
+ Telegram alerts (проблемы приходят сами)
+ Budget engine (система сама ограничивает перерасход)
```

Оценка: **5-7 рабочих дней** после запуска первого клиента.

---

*Документ создан: May 15, 2026*
*Следующий шаг: Production Deploy → XM Cyber validation → Telegram Bot*
