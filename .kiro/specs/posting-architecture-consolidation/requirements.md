# Requirements Document

## Introduction

Консолидация архитектуры постинга в RAMP. Система органически обросла четырьмя каналами доставки контента в Reddit (PRAW через proxy, email-задачи, browser extension, OAuth). Данная спецификация определяет унифицированную модель доставки с чёткими приоритетами каналов, цепочкой fallback, правилами маршрутизации и планом перехода из текущего состояния в целевое.

**Текущее состояние (июнь 2026):**
- Direct PRAW posting — FROZEN (`POSTING_DISABLED=true`, покупка proxy отложена)
- Email task delivery — PRIMARY канал (3 аватара полностью автоматизированы)
- Browser Extension — спецификация готова, код не написан
- OAuth posting — ожидает одобрения Reddit, отложен

**Целевое состояние:**
- Browser Extension — PRIMARY канал (zero-friction, zero-cost инфраструктура)
- Email task delivery — FALLBACK канал (когда extension offline)
- Direct PRAW posting — DEPRECATED (код сохранён как холодный резерв)
- OAuth — DEFERRED (активируется только если Reddit одобрит + бизнес решит)

## Glossary

- **Delivery_Channel**: Механизм доставки одобренного контента из RAMP в Reddit (extension, email, praw, oauth)
- **Channel_Router**: Компонент, определяющий какой Delivery_Channel использовать для конкретной задачи
- **Extension_Session**: Активная сессия browser extension на машине executor
- **Executor**: Человек, владеющий Reddit-аккаунтом аватара, ответственный за постинг
- **ExecutionTask**: Модель задачи на постинг (уже существует в системе)
- **Fallback_Chain**: Упорядоченный список каналов для попытки доставки при недоступности основного
- **Channel_Health**: Статус работоспособности канала (online, degraded, offline)
- **Cold_Reserve**: Код, который не выполняется в production, но сохранён для экстренной реактивации
- **EPG_Slot**: Запланированный слот публикации из EPG Portfolio Manager
- **Dispatch_Window**: Временное окно доставки задачи executor [scheduled_at - 5min, scheduled_at + 30min]
- **RAMP_Backend**: Серверная часть RAMP (FastAPI + Celery)
- **Posting_Event**: Аудит-запись попытки постинга (модель PostingEvent)

## Requirements

### Requirement 1: Единая модель маршрутизации каналов

**User Story:** Как оператор RAMP, я хочу единую точку принятия решений о канале доставки для каждой задачи, чтобы система предсказуемо выбирала оптимальный путь без ручного вмешательства.

#### Acceptance Criteria

1. WHEN an ExecutionTask is created, THE Channel_Router SHALL determine the delivery_channel within 5 seconds based on the executor's Extension_Session registration status and executor_email_verified flag
2. THE Channel_Router SHALL evaluate channels in fixed priority order: extension → email → manual_hold
3. WHILE an Extension_Session for the target executor is online (heartbeat received within the last 90 seconds) and authenticated for the correct Reddit account matching the avatar's reddit_username, THE Channel_Router SHALL route the task to the extension channel
4. WHILE an Extension_Session is offline for more than 30 minutes, THE Channel_Router SHALL fall back to the email channel if executor_email_verified is true
5. IF an Extension_Session is offline for less than 30 minutes, THEN THE Channel_Router SHALL hold the task (status=pending_reconnect) for up to 30 minutes before falling back; WHEN the 30-minute hold expires without reconnection, the task SHALL be re-routed to email
6. IF the executor has no registered Extension_Session and no verified executor_email, THEN THE Channel_Router SHALL place the task in manual_hold status and emit a notification to the operator
7. THE Channel_Router SHALL record the routing decision (channel chosen, reason, timestamp) in the ExecutionTask record
8. IF the Channel_Router selects email as the delivery channel but executor_email_verified is false, THEN the Channel_Router SHALL skip email and place the task in manual_hold status

#### Correctness Properties

- **Determinism**: Given identical Extension_Session state and executor configuration, the Channel_Router SHALL always produce the same routing decision
- **No-Task-Loss**: Every created ExecutionTask SHALL reach one of: delivered_to_extension, delivered_to_email, or manual_hold within 35 minutes of creation
- **Priority Invariant**: A task SHALL never be routed to email while the executor's Extension_Session is online and authenticated for the correct account

### Requirement 2: Приоритет каналов и состояния

**User Story:** Как владелец системы, я хочу явно определённые состояния каналов и правила приоритизации, чтобы при деградации одного канала система автоматически переключалась на следующий.

#### Acceptance Criteria

1. THE RAMP_Backend SHALL maintain a Channel_Health status for each delivery channel per executor: online, degraded, or offline — where the extension channel status is derived from heartbeat recency, and the email channel status is derived from the last 3 delivery attempts (online if at least 1 of the last 3 succeeded, degraded if all 3 failed within the last 30 minutes, offline if all 3 failed within the last 10 minutes or the Brevo API is unreachable)
2. WHILE the extension channel is online (heartbeat received within the last 60 seconds), THE Channel_Router SHALL route all tasks (content and system actions) exclusively to the extension channel
3. WHILE the extension channel is degraded (last heartbeat received between 60 and 120 seconds ago), THE Channel_Router SHALL route system actions (CQS probes, health probes) to the extension channel and route content actions (comment posting) to the email channel
4. WHILE the extension channel is offline (no heartbeat received for more than 120 seconds), THE Channel_Router SHALL route all tasks to the email channel
5. THE RAMP_Backend SHALL evaluate Channel_Health for the extension channel on every heartbeat receipt and on every 30-second polling cycle, transitioning the status within 5 seconds of the condition being met (online: heartbeat age ≤ 60s; degraded: heartbeat age 61-120s; offline: heartbeat age > 120s)
6. IF the email channel fails delivery (Brevo API error or HTTP status 4xx/5xx) for a specific executor, THEN THE RAMP_Backend SHALL retry once after 5 minutes and then mark the task as delivery_failed if the retry also fails
7. IF both the extension channel and the email channel are offline for a given executor, THEN THE RAMP_Backend SHALL hold pending tasks in a queue (maximum 50 tasks, oldest discarded first when full) and attempt delivery on whichever channel transitions to online or degraded first, re-evaluating channel status every 60 seconds
8. WHEN the extension channel transitions from online to degraded or offline, THE Channel_Router SHALL not reassign tasks that are already in EXECUTING state on the extension, but SHALL route all new tasks according to the updated channel status

#### Correctness Properties

- **State Completeness**: Channel_Health SHALL always be one of exactly three states: online, degraded, offline — no undefined/null states
- **Monotonic Transition**: State transitions SHALL follow heartbeat age thresholds without hysteresis (no oscillation guard needed since heartbeat is periodic)
- **In-Flight Safety**: Tasks already executing on a channel SHALL never be interrupted by a channel state transition

### Requirement 3: Поле delivery_channel на ExecutionTask

**User Story:** Как разработчик, я хочу чтобы каждая ExecutionTask явно хранила выбранный канал доставки, чтобы можно было отслеживать эффективность каналов и аудировать решения маршрутизации.

#### Acceptance Criteria

1. THE ExecutionTask model SHALL include a delivery_channel field with allowed values: extension, email, praw, manual_hold — with a default value of "email" matching the existing column definition
2. THE ExecutionTask model SHALL include a routing_reason field (String, max 255 chars) with structured format: "{channel_selected}:{condition}" (e.g., "extension:session_online", "email:extension_offline_35m", "manual_hold:no_channel_available")
3. THE ExecutionTask model SHALL include a channel_switched_at timestamp (nullable DateTime with timezone) that is NULL when no fallback has occurred and set to the UTC timestamp of the most recent channel switch
4. WHEN a task is re-routed from one channel to another due to fallback, THE RAMP_Backend SHALL update delivery_channel to the new channel, prepend the original channel to routing_reason (format: "fallback_from:{original_channel}:{reason} → {new_channel}:{new_reason}"), and set channel_switched_at to the current UTC timestamp
5. THE Posting_Dashboard SHALL expose delivery_channel statistics: count of tasks per channel per calendar day (Asia/Jerusalem), fallback rate (tasks with non-null channel_switched_at / total tasks dispatched) per calendar day, and average time between task creation and first delivery attempt per channel

#### Correctness Properties

- **Audit Completeness**: Every ExecutionTask SHALL have a non-null delivery_channel and routing_reason from the moment Channel_Router processes it
- **Temporal Ordering**: channel_switched_at SHALL always be later than the task's created_at timestamp

### Requirement 4: Deprecation Direct PRAW Posting

**User Story:** Как владелец системы, я хочу формально депрекировать Direct PRAW posting, сохранив код как холодный резерв, чтобы не нести операционные расходы на proxy но иметь возможность реактивации.

#### Acceptance Criteria

1. THE RAMP_Backend SHALL keep POSTING_DISABLED=true as the default value in production environment configuration for the praw channel, requiring a manual environment variable change and redeployment to override
2. THE RAMP_Backend SHALL retain all posting safety gates code (posting_safety.py, 9 gates) without modification
3. THE RAMP_Backend SHALL retain praw_factory.py, timing_engine.py, and posting.py in the codebase as Cold_Reserve
4. IF the system setting auto_posting_channel is not explicitly set to "praw", THEN THE Channel_Router SHALL reject the praw channel during channel selection and proceed to the next channel in the fallback chain
5. IF the auto_posting_channel setting equals "praw" AND POSTING_DISABLED is false AND the avatar has a non-empty proxy_url value stored in its configuration, THEN THE Channel_Router SHALL allow direct PRAW posting for that avatar
6. WHEN a Cold_Reserve code path executes (praw_factory creates a client instance or posting.py initiates a post attempt), THE RAMP_Backend SHALL log a warning-level ActivityEvent containing the avatar_id, task_id, and the specific Cold_Reserve function invoked
7. IF the auto_posting_channel setting equals "praw" AND POSTING_DISABLED is true, THEN THE Channel_Router SHALL reject the praw channel, log a warning-level event indicating the conflict, and fall back to the next available channel

#### Correctness Properties

- **Default Safety**: Without explicit opt-in (auto_posting_channel="praw" + POSTING_DISABLED=false + proxy configured), PRAW channel SHALL never be selected
- **Code Preservation**: All Cold_Reserve files SHALL pass type checking and import successfully even when not actively used

### Requirement 5: Интеграция Browser Extension как primary канала

**User Story:** Как оператор RAMP, я хочу чтобы browser extension стал основным каналом доставки, при этом существующий flow email-задач продолжал работать как fallback.

#### Acceptance Criteria

1. WHILE an executor has an Extension_Session with a heartbeat received within the last 90 seconds, THE RAMP_Backend SHALL route new tasks for that executor's active Reddit account to the extension channel instead of the email channel
2. THE RAMP_Backend SHALL deliver tasks to the extension via the existing polling endpoint (GET /api/extension/tasks)
3. WHEN a task is delivered to the extension, THE RAMP_Backend SHALL set a lease_expires_at on the task equal to the task's scheduled_at plus the configured lease duration (default: 15 minutes), after which the task is eligible for fallback re-routing
4. IF lease_expires_at passes without an execution report from the extension, THEN THE RAMP_Backend SHALL create a new email delivery for the same task using the existing email task dispatch flow and mark the extension delivery attempt as expired
5. THE Extension SHALL report task execution results (success with permalink, or failure with reason) to the RAMP_Backend via POST /api/extension/report before lease_expires_at
6. WHEN the extension reports success with a permalink, THE RAMP_Backend SHALL update the draft status to posted and record the reddit_comment_url without requiring draft reconciliation
7. IF an executor has no registered Extension_Session or the last heartbeat is older than 90 seconds, THEN THE RAMP_Backend SHALL deliver tasks exclusively via the email channel with no delay or holding period

#### Correctness Properties

- **Lease Expiry Guarantee**: Every task delivered to extension SHALL either receive an execution report OR be re-routed to email — no task can be permanently stuck
- **Single Execution**: A task SHALL not be simultaneously active on both extension and email channels; email fallback begins only AFTER lease expires
- **Permalink Authority**: When extension reports a permalink, that value becomes authoritative — draft reconciliation SHALL NOT overwrite it

### Requirement 6: Совместное существование каналов (Transition Period)

**User Story:** Как оператор RAMP, я хочу чтобы в переходный период (до полного покрытия extension) система корректно обслуживала аватаров через разные каналы одновременно.

#### Acceptance Criteria

1. THE RAMP_Backend SHALL support mixed-mode operation where some avatars use extension and others use email within the same client, with no dependency between one avatar's channel selection and another's
2. THE Channel_Router SHALL make per-avatar routing decisions at task creation time based on that avatar's executor capabilities (has online Extension_Session, has verified executor_email, has neither)
3. IF an avatar has no verified executor_email configured AND no registered Extension_Session for its executor, THEN THE Channel_Router SHALL place tasks for that avatar in manual_hold status and emit a notification to the operator indicating the avatar identifier and missing capability
4. THE RAMP_Backend SHALL provide an admin UI view showing per-avatar channel assignment and readiness with one of the following statuses per avatar: extension_online, extension_offline, email_configured, manual_hold (no channel available)
5. WHEN a new executor registers their Extension_Session, THE Channel_Router SHALL route subsequent tasks for that executor's avatars to the extension channel within 60 seconds of registration
6. THE RAMP_Backend SHALL not require all avatars to use the same channel — each avatar routes independently based on its executor's available channels
7. WHEN an avatar's executor capabilities change (executor_email verified or Extension_Session registered), THE Channel_Router SHALL re-evaluate any tasks in manual_hold status for that avatar and route them to the newly available channel within 60 seconds

#### Correctness Properties

- **Independence**: Channel selection for avatar A SHALL never block, delay, or influence channel selection for avatar B
- **Manual Hold Release**: Tasks in manual_hold SHALL be released within 60 seconds once a channel becomes available for that avatar's executor
- **No Silent Drops**: An avatar with no channel available SHALL always have its tasks in manual_hold (not silently discarded)

### Requirement 7: Наблюдаемость и метрики каналов

**User Story:** Как оператор RAMP, я хочу видеть производительность каждого канала доставки в реальном времени, чтобы принимать решения о масштабировании и расследовать проблемы.

#### Acceptance Criteria

1. THE Posting_Dashboard SHALL display per-channel metrics updated at intervals no greater than 60 seconds: tasks delivered (count of ExecutionTasks with delivery attempts sent), tasks completed (count of ExecutionTasks reaching status "verified" or "submitted"), tasks failed (count of ExecutionTasks reaching status "expired" or "failed"), and average latency in seconds measured from task created_at to the timestamp of the first successful delivery attempt, broken down by delivery_channel value ("extension", "email")
2. THE Posting_Dashboard SHALL display channel health status per executor: for extension channel — online (heartbeat received within the last 90 seconds) or offline (no heartbeat for more than 90 seconds); for email channel — configured (executor_email present and executor_email_verified is true) or not configured (executor_email absent or executor_email_verified is false)
3. WHEN the RAMP_Backend performs a channel fallback (delivery_channel changed from "extension" to "email" because extension was offline for more than 30 minutes), THE RAMP_Backend SHALL emit an ActivityEvent of type "channel_fallback" containing: original_channel ("extension"), fallback_channel ("email"), reason (one of: "extension_offline", "extension_lease_expired", "extension_error"), avatar_username, and task_id
4. THE RAMP_Backend SHALL compute and display on the Posting_Dashboard the daily fallback rate as: (count of tasks that triggered a channel_fallback ActivityEvent in a calendar day, 00:00-23:59 Asia/Jerusalem) divided by (total tasks dispatched in the same calendar day) multiplied by 100, rounded to 1 decimal place, with data retained for a rolling 30-day window
5. WHEN the daily fallback rate exceeds 30% and at least 10 tasks were dispatched in the same 24-hour calendar day (00:00-23:59 Asia/Jerusalem), THE RAMP_Backend SHALL emit a high-severity alert to the operator via the configured notification channel within 60 seconds of the threshold being crossed

#### Correctness Properties

- **Metric Freshness**: Dashboard metrics SHALL reflect state no older than 60 seconds
- **Alert Accuracy**: Fallback rate alert SHALL only fire when both conditions are met (>30% AND ≥10 tasks) — no false positives from low-volume days

### Requirement 8: Plan перехода (Transition Roadmap)

**User Story:** Как владелец системы, я хочу чёткий порядок шагов для перехода из текущего состояния (email-only) в целевое (extension-primary + email-fallback), чтобы каждый шаг был безопасным и откатываемым.

#### Acceptance Criteria

1. THE RAMP_Backend SHALL support a system setting posting_architecture_phase with values: phase_1_email_only, phase_2_extension_pilot, phase_3_extension_primary, phase_4_extension_default, with a default value of phase_1_email_only stored in the system_settings table
2. WHILE posting_architecture_phase equals phase_1_email_only, THE Channel_Router SHALL route all tasks to email (current behavior, no code change needed)
3. WHILE posting_architecture_phase equals phase_2_extension_pilot, THE Channel_Router SHALL route tasks to extension only for avatars whose reddit_username is listed in the extension_pilot_avatars system setting (comma-separated list), and route all other tasks to email
4. WHILE posting_architecture_phase equals phase_3_extension_primary, THE Channel_Router SHALL route tasks to extension for all executors with an Extension_Session that has sent a heartbeat within the last 120 seconds, and route tasks to email for executors without such a session
5. WHILE posting_architecture_phase equals phase_4_extension_default, THE Channel_Router SHALL route tasks to extension for all executors with a registered Extension_Session that has sent a heartbeat within the last 30 minutes, and route tasks to email only for executors with no registered Extension_Session
6. THE RAMP_Backend SHALL allow rollback from any phase to the previous phase via system setting change without code deployment
7. WHEN posting_architecture_phase is changed, THE Channel_Router SHALL apply the new routing rules only to tasks created after the change; tasks already assigned to a delivery channel SHALL continue delivery on their original channel

#### Correctness Properties

- **Phase Monotonicity**: Changing the phase setting SHALL affect only future routing decisions — no retroactive re-routing of in-flight tasks
- **Instant Rollback**: Reverting to a previous phase SHALL take effect within 60 seconds without any code redeployment or service restart
- **Pilot Containment**: In phase_2, ONLY avatars listed in extension_pilot_avatars SHALL receive extension routing — no accidental expansion

### Requirement 9: OAuth канал — формальный статус Deferred

**User Story:** Как владелец системы, я хочу формально зафиксировать статус OAuth-канала, чтобы не тратить ресурсы на его развитие до явного бизнес-решения.

#### Acceptance Criteria

1. THE RAMP_Backend SHALL retain the OAuth callback endpoint (GET /api/oauth/reddit/callback) in the codebase without modification
2. THE RAMP_Backend SHALL retain the RedditApp model with OAuth fields (access_token, refresh_token) without modification
3. THE Channel_Router SHALL never select oauth as delivery_channel unless a system setting oauth_posting_enabled is explicitly set to "true"; IF the setting is absent or has any value other than "true", THEN THE Channel_Router SHALL treat oauth as unavailable
4. IF oauth_posting_enabled is "true" AND the avatar has a non-null, non-expired OAuth access_token in its associated RedditApp record, THEN THE Channel_Router SHALL allow oauth as a delivery option with priority below extension and above email
5. THE RAMP_Backend SHALL display the OAuth channel status as "deferred — pending Reddit approval" in the admin settings UI alongside the oauth_posting_enabled setting, visible to owner and partner roles

#### Correctness Properties

- **Default Disabled**: Without explicit oauth_posting_enabled="true", OAuth channel SHALL never appear in routing decisions
- **Token Validity**: OAuth channel SHALL only be selected when the token is non-null AND not expired — expired tokens SHALL be treated as unavailable
