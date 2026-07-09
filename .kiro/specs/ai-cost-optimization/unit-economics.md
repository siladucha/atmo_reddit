# RAMP AI Pipeline — Как работает и сколько стоит

## Путь комментария (от скрейпа до поста)

```
SCRAPE → SCORE → SELECT PERSONA → GENERATE → EDIT → REVIEW → POST
  free    $0.001    $0.002         $0.04      $0.002   human    free
```

---

## 1. Scraping (бесплатно)

**Что:** PRAW (Reddit API) собирает свежие посты из подписанных сабреддитов.
**Модель:** Нет (чистый API).
**Стоимость:** $0.
**Частота:** Каждые 6 часов.

---

## 2. Scoring — оценка релевантности ($0.001/пост)

**Что:** AI решает: «engage» / «monitor» / «skip».
**Модель:** Gemini 2.5 Flash ($0.15/1M in, $0.60/1M out).
**Стоимость:** ~$0.0007/пост.
**Месяц (1 avatar):** ~600 постов = **$0.42/мес**

---

## 3. Persona Selection — выбор аватара ($0.002/пост)

**Что:** AI выбирает лучший аватар для ответа.
**Модель:** Gemini 2.5 Flash (перенесено с Sonnet 8 июля).
**Стоимость:** ~$0.0014/выбор.
**Месяц (1 avatar):** $0 (пропускается). **2+ avatars:** ~$0.21-0.42/мес.

---

## 4. Comment Generation — написание ($0.04/комментарий)

**Что:** AI пишет комментарий от лица аватара. Единственная операция на дорогой модели.
**Модель:** Claude Sonnet 4 ($3/1M in, $15/1M out).
**Стоимость:** ~$0.039/комментарий.
**Месяц (Phase 1):** 90 × $0.039 = **$3.51** | **Месяц (Phase 2):** 210 × $0.039 = **$8.19**

---

## 5. Editing — чистка ($0.0004/комментарий)

**Что:** AI убирает AI-артефакты (em-dashes, формальный язык).
**Модель:** Gemini 2.5 Flash (перенесено с Sonnet 8 июля).
**Стоимость:** ~$0.0004/правка.
**Месяц (Phase 2):** 210 × $0.0004 = **$0.08/мес**

---

## 6. Hobby Comments ($0.0002/комментарий)

**Что:** Короткие (20-60 слов) комментарии для прогрева кармы.
**Модель:** Gemini 2.5 Flash.
**Месяц (1 avatar):** 75 × $0.0002 = **$0.015/мес**

---

## 7. GEO/AEO Monitoring ($0.006/запрос)

**Что:** Perplexity проверяет упоминает ли AI-поиск бренд клиента.
**Модель:** Perplexity Sonar.
**Частота:** 6 промптов/день (ротация, полный цикл за 7 дней).
**Месяц (1 client):** 180 × $0.006 = **$1.08/мес**

---

## 8. Weekly Intelligence (<$0.10/мес)

**Что:** Subreddit risk profiling, emotional analysis, CQS, karma tracking.
**Модель:** Gemini Flash Lite (free) + PRAW.
**Стоимость:** ~$0.05/мес.

---

## 9. Клиентские запросы из портала ($0.07-0.25/мес)

**Что:** Действия клиента/партнёра в UI которые вызывают AI.

| Действие | Модель | Частота | $/мес |
|----------|--------|---------|-------|
| Strategy generation/refresh | Gemini Flash | 1-2×/мес | $0.01 |
| "Regenerate" draft | Claude Sonnet | 1-5×/мес | $0.04-0.20 |
| Discovery (weekly continuous) | Gemini Lite (free) | 20-30×/мес | $0.02 |
| Onboarding wizard (6 AI steps) | Gemini Flash | one-time | $0.01 |
| Tone calibration | Gemini Flash | one-time | $0.01 |
| Avatar onboarding (BYOA) | Claude Sonnet | one-time | $0.04 |
| **ИТОГО portal actions** | | | **$0.07-0.25/мес** |

Rate limits: Regenerate max 1/week, Strategy max 1/week, Pipeline trigger max 2/day.

---

## Сводная таблица: полная стоимость клиента/месяц

### Phase 1 (1 avatar, warming)

| Операция | $/мес |
|----------|-------|
| Scoring | $0.42 |
| Generation (hobby) | $0.02 |
| GEO monitoring | $1.08 |
| Intelligence | $0.05 |
| Portal actions | $0.07 |
| **ИТОГО** | **$1.64/мес** |

### Phase 2 (1 avatar, professional)

| Операция | $/мес |
|----------|-------|
| Scoring | $0.42 |
| Generation (pro, Sonnet) | $8.19 |
| Generation (hobby, Flash) | $0.02 |
| Editing (Flash) | $0.08 |
| GEO monitoring | $1.08 |
| Intelligence | $0.05 |
| Portal actions | $0.15 |
| **ИТОГО** | **$9.99/мес** |

### Phase 2 (2 avatars)

| Операция | $/мес |
|----------|-------|
| All pipeline (×2) | $17.80 |
| Persona selection | $0.42 |
| GEO (shared) | $1.08 |
| Portal actions | $0.20 |
| **ИТОГО** | **$19.50/мес** |

### Phase 2 (3 avatars)

| Операция | $/мес |
|----------|-------|
| All pipeline (×3) | $26.70 |
| Persona selection | $0.63 |
| GEO (shared) | $1.08 |
| Portal actions | $0.25 |
| **ИТОГО** | **$28.66/мес** |

---

## Маржинальность по планам

| Plan | Цена | Avatars | AI Cost | Infra share | Total cost | **Margin** |
|------|------|---------|---------|-------------|-----------|-----------|
| Seed $149 | $149 | 1 | $10 | $5 | $15 | **90%** |
| Starter $399 | $399 | 3 | $29 | $5 | $34 | **91%** |
| Growth $799 | $799 | 7 | $65 | $3 | $68 | **91%** |
| Scale $1499 | $1499 | 15 | $137 | $2 | $139 | **91%** |

---

## Формула

```
Себестоимость(клиент) = N_avatars × $8.50 + $1.08 (GEO) + $0.25 (portal) + $23/N_clients (infra)
                      ≈ N × $8.50 + $3.50 (при 5+ клиентах)
```

---

## Главный cost driver

**85% расходов = Comment Generation (Claude Sonnet).** Всё остальное на free/cheap моделях.

Дальнейшая оптимизация (если нужна):
- Gemini 2.5 Pro для generation → -70% cost (нужен quality test)
- Batch scoring (5 posts/1 prompt) → -80% scoring calls
- Semantic cache (v3.0) → -30-40% repeat context savings

---

## Инфраструктура

| Компонент | $/мес | Хватает на |
|-----------|-------|-----------|
| DigitalOcean droplet | $23 | 50 клиентов |
| DO Managed DB (at 5+ clients) | +$15 | 100 клиентов |
| **Total infra** | **$23-38** | |

---

## Масштабирование

| Clients | Avatars | AI/мес | Infra/мес | **Total** | Revenue | **Margin** |
|---------|---------|--------|-----------|-----------|---------|-----------|
| 1 | 1 | $10 | $23 | $33 | $149 | 78% |
| 5 | 10 | $96 | $23 | $119 | $1,995 | 94% |
| 10 | 20 | $192 | $23 | $215 | $3,990 | 95% |
| 50 | 100 | $960 | $38 | $998 | $39,950 | 97% |
