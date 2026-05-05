# Requirements Document

## Introduction

Единая очередь запросов к Reddit API для автоматического скрейпинга всех активных сабреддитов на SaaS-платформе. Текущая реализация использует жёстко заданный Celery Beat crontab (8:00 и 14:00 UTC), который запускает все скрейпы одновременно — это создаёт пиковые нагрузки на Reddit API, базу данных и увеличивает риск обнаружения. Новая архитектура заменяет пакетный cron-подход на непрерывную очередь с приоритизацией по «свежести» (staleness), глобальным rate limiter'ом и админской панелью мониторинга очереди. Система спроектирована для SaaS с неизвестным числом будущих клиентов и должна масштабироваться линейно.

## Glossary

- **Request_Queue**: Единая централизованная очередь всех запросов к Reddit API на платформе. Каждый элемент очереди представляет один сабреддит, который нужно скрейпить. Приоритет определяется по `last_scraped_at` — чем старше, тем выше приоритет.
- **Queue_Ticker**: Celery Beat задача, которая срабатывает каждые 1–2 минуты и извлекает из Request_Queue следующий элемент для обработки.
- **Rate_Limiter**: Глобальный ограничитель частоты запросов к Reddit API, реализованный через Redis. Конфигурируемый лимит запросов в минуту.
- **Freshness_Window**: Настраиваемый интервал (в часах), в течение которого сабреддит считается «свежим». По умолчанию — 12 часов. Если `last_scraped_at` старше Freshness_Window, сабреддит считается Stale_Subreddit.
- **Stale_Subreddit**: Active_Subreddit, чей `last_scraped_at` старше Freshness_Window или равен `NULL`.
- **Staleness_Score**: Числовое значение приоритета элемента в очереди. Вычисляется как `NOW() - last_scraped_at` в секундах. Для сабреддитов с `last_scraped_at = NULL` — максимальный приоритет.
- **Scrape_Worker**: Celery задача, которая выполняет один запрос скрейпинга для одного сабреддита.
- **Scrape_Enabled_Setting**: Запись `SystemSetting` (ключ: `scrape_enabled`), хранящая булев флаг, управляющий активностью скрейпинга.
- **Rate_Limit_Setting**: Запись `SystemSetting` (ключ: `scrape_rate_limit_rpm`), хранящая максимальное число запросов к Reddit API в минуту.
- **Freshness_Window_Setting**: Запись `SystemSetting` (ключ: `scrape_freshness_window_hours`), хранящая размер окна свежести в часах.
- **Tick_Interval_Setting**: Запись `SystemSetting` (ключ: `scrape_tick_interval_seconds`), хранящая интервал тика Queue_Ticker в секундах.
- **Queue_Dashboard**: Раздел админ-панели для мониторинга состояния Request_Queue в реальном времени.
- **Active_Client**: Запись `Client` с `is_active = True`.
- **Active_Subreddit**: Запись `ClientSubreddit` с `is_active = True`.
- **Admin_User**: Пользователь с `is_superuser = True`.
- **Activity_Event**: Запись в таблице `activity_events` для логирования прозрачности пайплайна.
- **Distributed_Lock**: Redis-based блокировка на уровне отдельного сабреддита, предотвращающая параллельный скрейпинг одного и того же сабреддита.

## Requirements

### Requirement 1: Unified Request Queue

**User Story:** As an Admin_User, I want all Reddit API scraping requests to go through a single centralized queue, so that the system processes them sequentially with priority-based ordering instead of burst-firing all requests at once.

#### Acceptance Criteria

1. THE Request_Queue SHALL maintain a prioritized list of all Active_Subreddits across all Active_Clients that require scraping.
2. THE Request_Queue SHALL assign each element a Staleness_Score computed as the number of seconds since the subreddit's `last_scraped_at` timestamp.
3. WHEN a subreddit has `last_scraped_at = NULL`, THE Request_Queue SHALL assign the maximum Staleness_Score to that element.
4. WHEN the Queue_Ticker fires, THE Queue_Ticker SHALL select the single Active_Subreddit with the highest Staleness_Score from the Request_Queue and dispatch it to the Scrape_Worker.
5. WHEN multiple Active_Subreddits share the same Staleness_Score, THE Queue_Ticker SHALL select one deterministically (by subreddit name alphabetical order).
6. WHILE the Scrape_Enabled_Setting value is `"false"`, THE Queue_Ticker SHALL skip dispatching and log a message indicating that scraping is paused.
7. WHEN an Active_Subreddit's `last_scraped_at` is within the Freshness_Window, THE Queue_Ticker SHALL deprioritize that subreddit below all Stale_Subreddits.

### Requirement 2: Queue Ticker Configuration

**User Story:** As an Admin_User, I want to configure the tick interval and freshness window from the admin UI, so that I can tune scraping throughput without redeploying.

#### Acceptance Criteria

1. THE Tick_Interval_Setting SHALL store an integer value in seconds (range: 30–300) in the `system_settings` table with key `scrape_tick_interval_seconds`.
2. THE Tick_Interval_Setting SHALL default to `"60"` (one tick per minute) when no value is configured.
3. THE Freshness_Window_Setting SHALL store an integer value in hours (range: 1–168) in the `system_settings` table with key `scrape_freshness_window_hours`.
4. THE Freshness_Window_Setting SHALL default to `"12"` (12 hours) when no value is configured.
5. THE Scrape_Enabled_Setting SHALL store a string value of `"true"` or `"false"` in the `system_settings` table with key `scrape_enabled`.
6. THE Scrape_Enabled_Setting SHALL default to `"true"` when no value is configured.
7. WHEN an Admin_User updates the Tick_Interval_Setting, THE Queue_Ticker SHALL apply the new interval within 120 seconds without requiring a worker restart.
8. WHEN an Admin_User submits a value for the Tick_Interval_Setting outside the range 30–300, THE system SHALL reject the value and return a descriptive error message.
9. WHEN an Admin_User submits a value for the Freshness_Window_Setting outside the range 1–168, THE system SHALL reject the value and return a descriptive error message.

### Requirement 3: Global Rate Limiter

**User Story:** As an Admin_User, I want a global rate limiter on Reddit API requests, so that the platform stays within Reddit's rate limits and avoids detection from burst activity.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL enforce a configurable maximum number of Reddit API requests per minute across the entire platform.
2. THE Rate_Limit_Setting SHALL store an integer value (range: 1–60) in the `system_settings` table with key `scrape_rate_limit_rpm`.
3. THE Rate_Limit_Setting SHALL default to `"30"` (30 requests per minute) when no value is configured.
4. WHEN the Queue_Ticker attempts to dispatch a Scrape_Worker and the Rate_Limiter indicates the limit has been reached for the current minute, THE Queue_Ticker SHALL skip the dispatch and retry on the next tick.
5. THE Rate_Limiter SHALL use a Redis-based sliding window counter to track requests per minute.
6. WHEN the Rate_Limiter skips a dispatch, THE Queue_Ticker SHALL log a debug-level message indicating the rate limit was reached.
7. WHEN an Admin_User submits a value for the Rate_Limit_Setting outside the range 1–60, THE system SHALL reject the value and return a descriptive error message.

### Requirement 4: Concurrency Protection

**User Story:** As an Admin_User, I want the system to prevent the same subreddit from being scraped simultaneously by multiple workers, so that duplicate data and wasted API calls are avoided.

#### Acceptance Criteria

1. WHEN the Scrape_Worker begins processing a subreddit, THE Scrape_Worker SHALL acquire a Distributed_Lock specific to that subreddit (key pattern: `scrape_lock:{subreddit_name}`).
2. THE Distributed_Lock SHALL have a configurable TTL of 300 seconds (5 minutes) to prevent deadlocks from crashed workers.
3. IF the Distributed_Lock for a subreddit cannot be acquired, THEN THE Queue_Ticker SHALL skip that subreddit and select the next highest-priority Stale_Subreddit from the Request_Queue.
4. WHEN the Scrape_Worker completes processing a subreddit (success or failure), THE Scrape_Worker SHALL release the Distributed_Lock for that subreddit.
5. WHEN a Distributed_Lock expires due to TTL, THE Request_Queue SHALL allow that subreddit to be selected again on the next tick.

### Requirement 5: Scrape Execution and Transparency

**User Story:** As an Admin_User, I want each individual subreddit scrape to be logged as an Activity_Event, so that I have full visibility into what the queue is processing.

#### Acceptance Criteria

1. WHEN the Scrape_Worker starts processing a subreddit, THE Scrape_Worker SHALL record an Activity_Event with `event_type` = `"scrape"` and a message indicating the subreddit name and client name.
2. WHEN the Scrape_Worker completes processing a subreddit, THE Scrape_Worker SHALL update the subreddit's `last_scraped_at` to the current UTC timestamp.
3. WHEN the Scrape_Worker completes processing a subreddit, THE Scrape_Worker SHALL record an Activity_Event with `event_type` = `"scrape"` containing the subreddit name, posts found, new posts count, and duration in milliseconds.
4. IF the Scrape_Worker encounters an error during scraping, THEN THE Scrape_Worker SHALL record an Activity_Event with `event_type` = `"system"` containing the subreddit name, client name, and error details.
5. IF the Scrape_Worker encounters an error during scraping, THEN THE Scrape_Worker SHALL release the Distributed_Lock and allow the subreddit to be retried on a subsequent tick.
6. THE Scrape_Worker SHALL process each Active_Client's subreddits independently so that a failure for one client's subreddit does not prevent scraping of other subreddits.

### Requirement 6: Admin Queue Dashboard

**User Story:** As an Admin_User, I want a queue monitoring dashboard similar to RabbitMQ management UI, so that I can see the real-time state of the scraping queue and diagnose bottlenecks.

#### Acceptance Criteria

1. THE Queue_Dashboard SHALL display the total number of items currently in the Request_Queue.
2. THE Queue_Dashboard SHALL display the number of Stale_Subreddits (subreddits past their Freshness_Window).
3. THE Queue_Dashboard SHALL display the current processing speed in requests per minute, calculated from Activity_Events over the last 5 minutes.
4. THE Queue_Dashboard SHALL display a list of subreddits currently waiting in the queue, sorted by Staleness_Score descending, showing: subreddit name, client name, `last_scraped_at`, and Staleness_Score.
5. THE Queue_Dashboard SHALL indicate which subreddit is currently being processed (has an active Distributed_Lock).
6. THE Queue_Dashboard SHALL display the estimated time until the queue is empty, calculated as `(queue_depth / current_processing_speed_per_minute)` in minutes.
7. THE Queue_Dashboard SHALL display the current Rate_Limiter utilization as a percentage of the configured Rate_Limit_Setting.
8. THE Queue_Dashboard SHALL auto-refresh via HTMX polling every 30 seconds.
9. WHEN the Request_Queue is empty (all subreddits are within their Freshness_Window), THE Queue_Dashboard SHALL display a status message indicating all subreddits are fresh.

### Requirement 7: Scrape Enable/Disable Control

**User Story:** As an Admin_User, I want to pause and resume the scraping queue with a single toggle, so that I can quickly stop all scraping activity during incidents or maintenance.

#### Acceptance Criteria

1. WHEN an Admin_User sets the Scrape_Enabled_Setting to `"false"`, THE Queue_Ticker SHALL stop dispatching Scrape_Workers within 120 seconds.
2. WHEN an Admin_User sets the Scrape_Enabled_Setting to `"true"`, THE Queue_Ticker SHALL resume dispatching Scrape_Workers on the next tick.
3. THE Queue_Dashboard SHALL display the current state of the Scrape_Enabled_Setting as a prominent toggle (enabled/disabled).
4. WHEN the Scrape_Enabled_Setting is `"false"`, THE Queue_Dashboard SHALL display a visual warning banner indicating that scraping is paused.

### Requirement 8: Graceful Degradation

**User Story:** As an Admin_User, I want the scraping queue to handle infrastructure failures gracefully, so that temporary outages do not cause data loss or system instability.

#### Acceptance Criteria

1. IF the Redis connection is unavailable when the Queue_Ticker attempts to check the Rate_Limiter, THEN THE Queue_Ticker SHALL skip the current tick and retry on the next tick without crashing the Celery worker.
2. IF the database connection is unavailable when the Queue_Ticker queries for the next Stale_Subreddit, THEN THE Queue_Ticker SHALL log the error and skip the current tick without crashing the Celery worker.
3. WHEN a Scrape_Worker crashes or is interrupted, THE Distributed_Lock SHALL expire after its TTL (300 seconds), allowing the subreddit to be picked up on a subsequent tick.
4. IF the Reddit API returns a rate-limit response (HTTP 429), THEN THE Scrape_Worker SHALL record the event in an Activity_Event with `event_type` = `"system"` and release the Distributed_Lock without updating `last_scraped_at`.
5. IF the Reddit API returns a rate-limit response (HTTP 429), THEN THE Rate_Limiter SHALL temporarily reduce the effective rate limit by 50% for 5 minutes to allow recovery.
