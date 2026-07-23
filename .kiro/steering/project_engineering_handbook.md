---
inclusion: manual
---

# Project Engineering Handbook — Accumulated Lessons

Это накопленные знания из реального production проекта (RAMP, июль 2026).
Не теория — практика. Каждый пункт куплен ошибкой или инцидентом.

---

## 1. Архитектура и структура

### Services thin, routes thinner
- Роуты = только HTTP в/из. Вся логика в `services/`.
- Services = бизнес-логика. Никаких HTTP-объектов.
- Если service импортирует FastAPI — это нарушение.

### Hot Files — осторожно
Эти файлы трогает последний из параллельных сессий — и ломает остальных.
Редактируй их только по очереди:
- `main.py` — регистрация роутеров
- `models/__init__.py` — импорт моделей
- `tasks/worker.py` — регистрация Celery tasks
- `docker-compose.yml`
- `alembic/env.py`
- `tests/conftest.py`

### Миграции — одна за раз
Никогда не запускай `alembic revision` из двух сессий одновременно.
Результат: разветвление истории миграций, потеря данных при upgrade.
Правило: все модели готовы → одна миграция на всё → `alembic upgrade head`.

---

## 2. AI / LLM интеграция

### Единая точка входа — обязательно
Все LLM-вызовы ТОЛЬКО через один централизованный метод (`call_llm()` или аналог).
Никогда напрямую через `anthropic.messages.create()` или `openai.chat.completions.create()`.

Почему:
- Без централизации невозможно считать стоимость
- Без централизации невозможно поставить rate limit / circuit breaker
- Без централизации невозможно логировать все вызовы

### 3-слойная защита от runaway LLM
1. Per-task call counter (ContextVar, max 50 calls/task) — не зависит от Redis
2. Cost circuit breaker в Redis ($5 за 10 минут — после сброс)
3. Daily/hourly caps в Redis

Без этого один баг в retry-логике = $50 улетело пока ты спал.

### Логируй каждый вызов
После каждого успешного `call_llm()` → `log_ai_usage()`.
Без этого `/admin/ai-costs` показывает ноль. Баг обнаруживается через неделю.

### Hardcode модели — запрещено
Модель должна браться из DB (`system_settings`) или конфига, не из кода.
`model="claude-3-5-sonnet-20241022"` в service файле = технический долг с первого дня.

---

## 3. База данных

### SQLAlchemy 2.0 стиль
```python
# Правильно:
id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
name: Mapped[str] = mapped_column(String(200))
created_at: Mapped[datetime] = mapped_column(default=func.now())

# Неправильно (старый стиль):
id = Column(UUID, primary_key=True)
```

### Query scoping — с первого дня
Каждый запрос должен быть скопирован по `client_id` или аналогу.
Изоляция данных между клиентами/пользователями — не фича, это фундамент.
Если добавить потом — придётся переписывать 50 endpoints.

### Миграции — только additive первые 6 месяцев
ADD COLUMN = безопасно (старый код игнорирует).
DROP COLUMN / RENAME = опасно (требует deploy-координации).
Правило: не удаляй колонки пока не убедился что они не используются ни в одном месте.

---

## 4. Celery / Task Queue

### Beat = отдельный процесс, минимальные импорты
Beat должен только знать расписание — не импортировать весь app.
Иначе memory leak: Beat импортирует scipy/transformers/etc и съедает 500 MB.
Решение: `beat_app.py` импортирует только schedule, `worker.py` импортирует все tasks.

### Retry с exponential backoff — обязательно
```python
@celery_app.task(bind=True, max_retries=3)
def my_task(self):
    try:
        ...
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * 2 ** self.request.retries)
```
Без backoff: один сбой Redis → 1000 одновременных retry → DDoS своего же сервера.

### Distributed lock для singleton tasks
Если задача не должна выполняться дважды одновременно — Redis SETNX lock.
Без lock: Beat запускает task каждые 5 мин, предыдущий ещё не закончил → дубликаты данных.

---

## 5. Безопасность

### JWT + RBAC с первого дня
Не "потом добавим роли". Добавить RBAC к готовой системе = переписать 80% endpoints.
Минимум: owner / admin / user. Добавить roles на модель User в день 1.

### Шифрование чувствительных полей
Пароли, токены, API keys в БД — только Fernet/AES, не plain text.
Даже если "это внутренняя система". Особенно если это SaaS.

### Rate limiting на auth endpoints
`/login`, `/register`, `/forgot-password` — rate limit с первого дня.
Без него: credential stuffing за 2 часа перебирает 100K паролей.

### .env никогда в git
`.gitignore` должен быть создан до первого commit.
`.env.example` — да. `.env` — никогда.

---

## 6. Deploy и CI/CD

### Staging обязателен
Без staging: production — это первое место где запускается Docker build.
Один неправильный import = downtime для клиентов.

### Pre-flight checklist перед каждым deploy
1. Все .py компилируются без ошибок
2. Key imports работают (`from app.main import app`)
3. Alembic single head (нет разветвлений)
4. Тесты проходят
5. .env не в changeset

### Автоматический rollback
Deploy script должен: сохранить предыдущий image → deploy → health check → если fails → восстановить предыдущий.
Без rollback: каждый failed deploy = ручное SSH + паника.

### Watchdog для production
Внешний процесс (systemd timer, каждые 30s) проверяет: Redis up? DB up? App отвечает?
Если нет — перезапускает контейнер и шлёт Telegram alert.
Без watchdog: упал Beat в 3 ночи → никто не знает до утра.

---

## 7. Тестирование

### Тесты — только против production bugs
Каждый тест должен отвечать: "какой production-баг это предотвращает?"
Тесты ради coverage = мусор в CI pipeline.

### Red-Green для bug fixes
Нашёл баг → сначала пишешь тест который его воспроизводит (red) → чинишь код (green).
Без этого: баг вернётся через 2 недели и никто не поймёт почему.

### Критические тесты = gate для deploy
Есть 2-3 теста которые покрывают самые дорогие баги (потеря денег, нарушение изоляции данных).
Если они падают — deploy заблокирован. Без исключений.

### Mock внешние сервисы
LLM, Reddit API, Stripe — всегда mock в тестах.
Без mock: тесты стоят деньги, падают от rate limit, зависят от интернета.

---

## 8. Мониторинг и операции

### System Behavior Model (SBM) — 5-10 инвариантов
Определи заранее: что ВСЕГДА должно быть правдой о твоей системе?
Примеры:
- P1: Каждый активный клиент получает ≥1 output в неделю
- P2: Client A никогда не видит данные Client B
- P3: LLM cost ≤ $X в день
- P4: Между generate и publish всегда есть human approval

Каждый инцидент маппится на нарушение одного из этих инвариантов.
Без SBM: инциденты повторяются потому что ты фиксируешь симптом, не причину.

### Alert fatigue — главный враг ops
Если alert срабатывает чаще 1 раза в 3 дня — его игнорируют.
Лучше 3 точных alert чем 30 шумных.

### Engineering Memory
Каждый баг: проблема → root cause → fix → rule → protection.
Через 6 месяцев: поиск по базе багов найдёт паттерн раньше чем ты.

---

## 9. Параллельная работа (Multi-Session)

### Принцип: модули параллельно, подключение по очереди
- Параллельно: новый service, модель, роут, шаблон, тесты — каждый в своих файлах
- По очереди: регистрация в main.py, __init__.py, worker.py, миграции

### Контракт на подключение
Каждая параллельная сессия в конце работы пишет:
```
## Подключение к системе
1. В main.py добавить: from app.routes.X import router_X; app.include_router(router_X)
2. В models/__init__.py добавить: from app.models.X import ModelX
3. Нужна миграция: alembic revision --autogenerate -m "add X"
```

### При конфликте в файле
Перечитай файл → адаптируй свои изменения, не перезаписывай чужие.
Если не можешь адаптировать → стоп, сообщи пользователю.

---

## 10. Коммуникация и процесс

### Один источник правды
Документация в коде (docstrings) или в steering — не в обоих местах.
Два источника = они расходятся за 2 недели.

### ADR для нетривиальных решений
Architecture Decision Record: проблема → варианты → решение → последствия.
Без ADR: через 3 месяца никто не помнит почему выбрали Redis а не Kafka.

### Steering файлы — живой документ
Каждый инцидент → обновление steering.
Steering который не обновляется = бесполезный.

### Не автоматизируй то что происходит раз в месяц
Автоматизация стоит времени. ROI = (время_задачи × частота) / время_автоматизации.
Если задача занимает 5 мин и бывает раз в месяц → не автоматизируй.
