# CI/CD Pipeline — Описание для аналитиков

## Обзор

Переход от ручного деплоя (rsync с Мака на прод) к автоматизированному CI/CD пайплайну через GitHub Actions.

---

## Текущая схема (до внедрения)

```
Разработчик (Mac)
    ↓ rsync напрямую
Production (161.35.27.165)
```

**Проблемы:**
- Код попадает на прод без проверки тестами
- Нет staging верификации — прод = первое место где код запускается в Docker
- Один опечатка = даунтайм для клиентов
- Нет аудита кто что задеплоил и когда
- Откат = ручной rsync предыдущей версии

---

## Целевая схема

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitHub Repository                             │
│                    (siladucha/atmo_reddit)                           │
└─────────────────────────────────────────────────────────────────────┘
         │                        │                        │
         │ push to branch         │ merge to main          │ manual approve
         ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   CI Workflow   │    │  Deploy to Staging   │    │  Deploy to Prod     │
│                 │    │                      │    │                     │
│ • Import check  │    │ • rsync → staging    │    │ • rsync → prod      │
│ • Alembic heads │    │ • docker build       │    │ • watchdog grace     │
│ • pytest suite  │    │ • docker up          │    │ • docker build       │
│ • Report        │    │ • health check       │    │ • docker up          │
│                 │    │ • smoke tests        │    │ • health check       │
│ ❌ = блокирует  │    │                      │    │ • version verify     │
│    merge        │    │ auto на merge в main │    │                     │
└─────────────────┘    └─────────────────────┘    └─────────────────────┘
                              staging.gorampit.com        gorampit.com
                              167.172.191.42              161.35.27.165
```

---

## Компоненты пайплайна

### 1. CI Workflow (`ci.yml`)

**Триггер:** любой `git push` или Pull Request в main.

**Что проверяет:**
| Проверка | Зачем | Блокирует? |
|----------|-------|-----------|
| Python imports | Ловит missing deps, circular imports, typos | Да |
| Alembic single head | Ловит branched migrations (конфликты) | Да |
| pytest suite (~1600 тестов) | Ловит регрессии: сломанная логика, schema drift, API changes | Да |
| Test report (JUnit XML) | Видимость results в GitHub UI | — |

**Инфраструктура CI:**
- PostgreSQL 16 + pgvector (service container)
- Redis 7 (service container)
- Python 3.11
- pip cache (ускоряет повторные прогоны)

**Время выполнения:** ~4-5 минут.

---

### 2. Deploy to Staging (`deploy-staging.yml`)

**Триггер:** автоматический при merge в `main`.

**Шаги:**
1. SSH на staging сервер
2. rsync кода (исключая .env, tests, .git)
3. `docker compose build` (пересборка образа)
4. `docker compose up -d` (запуск новых контейнеров)
5. Wait 10s (миграции + startup)
6. `curl /health` — проверка что приложение живое
7. Verify version matches commit

**При ошибке:** workflow fails, notification, prod deploy заблокирован.

---

### 3. Deploy to Production (`deploy-prod.yml`)

**Триггер:** ручной approve (кнопка в GitHub UI).

**Предусловия:**
- CI зелёный ✓
- Staging deploy зелёный ✓
- Reviewer (Max) нажал "Approve" в GitHub Environment `production`

**Шаги:**
1. Signal watchdog (grace period 90s — отключает мониторинг на время деплоя)
2. SSH на prod сервер
3. rsync кода
4. Update watchdog script на хосте
5. `docker compose build`
6. `docker compose up -d`
7. Wait 10s
8. `curl /health` — health check (3 retry)
9. Verify version
10. Check no startup errors in logs

**При ошибке:** автоматический rollback alert, manual intervention required.

---

## Environments

| Среда | Сервер | URL | Назначение |
|-------|--------|-----|-----------|
| **Development** | Локальный Mac | localhost:8000 | Разработка, отладка |
| **CI** | GitHub Actions (ubuntu) | — | Автотесты, валидация |
| **Staging** | DigitalOcean 167.172.191.42 | staging.gorampit.com | Pre-prod проверка в Docker |
| **Production** | DigitalOcean 161.35.27.165 | gorampit.com | Живая система с клиентами |

---

## Секреты и доступы (GitHub Secrets)

| Secret | Назначение |
|--------|-----------|
| `STAGING_SSH_KEY` | Приватный ключ для SSH на staging |
| `PROD_SSH_KEY` | Приватный ключ для SSH на production |
| `STAGING_HOST` | IP staging сервера |
| `PROD_HOST` | IP production сервера |

---

## Правила ветвления (Git Flow)

| Ветка | Правило |
|-------|---------|
| `main` | Production-ready. Merge только через CI. No force-push. |
| `feature/*` | Рабочие ветки. CI бежит на каждый push. Может быть сломанной. |
| Hotfix в main | Допускается с пройденным CI (без PR для срочных фиксов). |

---

## Защита от регрессий

| Слой | Что ловит | Когда |
|------|-----------|-------|
| **CI тесты** | Import errors, logic bugs, schema mismatches | Каждый push |
| **Alembic check** | Branched migrations, missing downgrade | Каждый push |
| **Staging deploy** | Docker build failures, missing deps, migration errors | Merge в main |
| **Staging health** | App crash on startup, broken routes | После deploy |
| **Prod health** | Runtime errors after deploy | После deploy |
| **Watchdog** | Container death, OOM, disk full | Каждые 30 сек (systemd) |

---

## Метрики и мониторинг

| Метрика | Где видно |
|---------|-----------|
| CI pass rate | GitHub Actions tab |
| Deploy frequency | GitHub Actions history |
| Time from commit to prod | Staging deploy time + approve wait + prod deploy |
| Rollback frequency | Git revert commits |
| Test count & coverage | JUnit XML artifact |

---

## План перехода

| Фаза | Что | Когда | Результат |
|------|-----|-------|-----------|
| 1 | CI (тесты на push, не блокирует) | День 1 | Видимость failures |
| 2 | Починить тесты (73 broken → 0) | День 1-2 | CI зелёный |
| 3 | CI блокирует merge | День 2 | Защита от регрессий |
| 4 | Auto-deploy staging | День 3 | Staging всегда актуален |
| 5 | Manual approve → prod | День 3 | Прод защищён |
| 6 | Убрать ручной rsync | День 4 | Единый flow |

---

## Rollback процедура

**Если prod deploy сломался:**

1. **Быстрый:** `git revert HEAD` → push → CI → merge → auto staging → approve prod
2. **Срочный (bypass CI):** SSH на прод → `git checkout HEAD~1` на host → rebuild

**Если staging сломался:**
- Не влияет на клиентов. Фиксить спокойно, re-push.

---

## FAQ

**Q: Можно ли деплоить в обход CI?**
A: Нет. Даже hotfix идёт через push → CI → merge. Единственное исключение: SSH на прод для критического fix (документируется как incident).

**Q: Сколько длится полный цикл commit → prod?**
A: ~10 минут (CI 5 мин + staging 2 мин + approve + prod 2 мин).

**Q: Что если тест flaky (иногда падает)?**
A: Помечается `pytest.mark.flaky` с retry. Если не стабилизируется за неделю — удаляется или переписывается.

**Q: Кто может approve prod deploy?**
A: Только Max (owner). Настраивается в GitHub Environment → Required reviewers.
