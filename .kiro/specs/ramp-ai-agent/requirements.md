# Requirements Document

## Introduction

RAMP AI Agent v0.1 — Read-Only Intelligence Layer (версия 0.5.0). Первая рабочая версия AI-агента платформы RAMP, работающего исключительно в режиме наблюдения (Observation & Intelligence Mode). Агент НЕ является чат-ботом или AI-ассистентом — это начало RAMP AI Operating System, слоя управления бизнесом. Первая версия НЕ принимает решений и НЕ изменяет состояние системы. Задача: научиться видеть, понимать и объяснять что происходит в продукте и бизнесе.

Агент строится поверх существующей инфраструктуры (Daily Ops Review Phase 1: signal_collector, cost_governor; SBM с 12 свойствами; alert_aggregation, billing_dashboard, llm_quality_monitor) и формализует разрозненную observability в единый AI-driven intelligence layer.

Ключевой принцип: **Сначала агент должен научиться видеть, понимать и объяснять. Только потом — действовать.**

## Glossary

- **RAMP_AI_Agent**: Read-Only Intelligence Layer — подсистема, которая собирает события, анализирует их, группирует, находит отклонения от Happy Path и формирует рекомендации для оператора
- **Unified_Event**: Единая нормализованная запись о любом событии в системе, независимо от источника данных (PostgreSQL, logs, Celery, Redis, LLM API, webhooks)
- **Business_Process_Map**: Документ, описывающий нормальное функционирование каждого ключевого бизнес-процесса (Happy Path, состояния, переходы, временные ограничения)
- **Happy_Path**: Ожидаемый нормальный сценарий прохождения бизнес-процесса от начала до конца без отклонений
- **Deviation**: Отклонение реального поведения от ожидаемого Happy Path, обнаруженное агентом через корреляцию событий
- **Business_Incident**: Агрегированное бизнес-событие, объединяющее множество технических сигналов в единый понятный инцидент с оценкой влияния на клиента
- **Daily_Report**: Ежедневный управленческий отчёт, содержащий обнаруженные инциденты, их приоритеты и рекомендации
- **Data_Source_Registry**: Реестр всех доступных источников данных с метаданными о качестве, полноте и способе подключения
- **Event_Collector**: Подсистема, собирающая сырые события из различных источников и нормализующая их в Unified_Event
- **Scenario_Analyzer**: Подсистема, реализующая конкретные сценарии анализа (Customer Success Risk, AI Reliability, AI FinOps)
- **Platform_Operator**: Max — технический сооснователь, основной получатель отчётов и рекомендаций агента
- **Customer_Success_Risk**: Сценарий обнаружения ситуации, когда пользователь не получил ожидаемую ценность (зарегистрировался, начал онбординг, не получил отчёт, не активировался)
- **AI_Reliability**: Сценарий мониторинга надёжности LLM-операций (таймауты, невалидный JSON, ретраи, ошибки API, рост латентности)
- **AI_FinOps**: Сценарий обнаружения аномальных расходов на AI (стоимость на клиента, стоимость операций, количество ретраев, превышение ожидаемого бюджета)

## Requirements

### Requirement 1: Data Sources Audit & Registry

**User Story:** As the Platform Operator, I want a complete map of all available data sources with metadata about each, so that the AI Agent knows where to find information about system behavior.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL maintain a Data_Source_Registry documenting each data source with: name, purpose, event types contained, connection method, data quality assessment, and sufficiency rating for analysis
2. THE Data_Source_Registry SHALL include entries for: PostgreSQL (all application tables), application logs (structured logging), Celery task events (task lifecycle, retries, failures), Redis (locks, heartbeats, counters), AI Usage logs (LLM requests, costs, quality outcomes), error and exception records, webhook events (Stripe billing), email delivery events (Brevo), and Reddit API interaction logs
3. WHEN a new data source is added to the platform, THE RAMP_AI_Agent SHALL provide an interface for registering the source in the Data_Source_Registry with required metadata fields
4. THE Data_Source_Registry SHALL store a freshness indicator for each source showing the timestamp of the last successfully ingested event from that source
5. IF a registered data source has not produced events for a period exceeding twice its expected event interval, THEN THE RAMP_AI_Agent SHALL flag that source as "stale" in the registry

### Requirement 2: Business Process Map — Happy Path Definition

**User Story:** As the Platform Operator, I want a documented map of what normal system operation looks like for each key business process, so that the AI Agent can detect deviations from expected behavior.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL store a Business_Process_Map defining Happy Path for each mandatory process: Signup, Onboarding, Report Generation, Customer Activation, Billing, and AI Request Pipeline
2. FOR EACH process in the Business_Process_Map, THE RAMP_AI_Agent SHALL define: ordered states, allowed transitions between states, expected events at each transition, maximum time constraints between states, possible deviation causes, and business consequences of deviation
3. THE Business_Process_Map SHALL define the Signup process Happy Path as: registration → email verification (within 48 hours) → first login → redirect to onboarding
4. THE Business_Process_Map SHALL define the Onboarding process Happy Path as: wizard step 1 (company URL) → step 2 (positioning) → step 3 (ICP) → step 4 (voice + keywords + subreddits) → step 5 (avatar connect) → step 6 (review + activate), with maximum 7 days total from start to completion
5. THE Business_Process_Map SHALL define the Customer Activation process Happy Path as: onboarding complete → first pipeline run → first draft generated → first draft approved → first comment posted, with maximum 14 days total
6. THE Business_Process_Map SHALL define the AI Request Pipeline process Happy Path as: request initiated → LLM call sent → response received (within 30 seconds) → response validated → result stored
7. WHEN the Business_Process_Map is updated, THE RAMP_AI_Agent SHALL validate that all defined transitions are reachable and no terminal dead-end states exist other than explicit end states

### Requirement 3: Unified Event Model

**User Story:** As the Platform Operator, I want all system events normalized into a single format regardless of their source, so that the AI Agent can correlate events across different subsystems.

#### Acceptance Criteria

1. THE Event_Collector SHALL normalize every ingested event into a Unified_Event with fields: id (UUID), event_type (string), timestamp (UTC datetime), source (data source name), entity_type (user, client, avatar, report, draft, etc.), entity_id (reference to the related entity), severity (info, warning, error, critical), and metadata (JSONB with source-specific additional data)
2. THE Event_Collector SHALL ingest events from PostgreSQL by monitoring activity_events table, ai_usage_log table, posting_events table, comment_drafts status changes, and client lifecycle changes
3. THE Event_Collector SHALL ingest Celery task events by monitoring task state transitions (sent, started, succeeded, failed, retried) and recording task name, duration, and failure reason
4. THE Event_Collector SHALL ingest LLM interaction events by reading ai_usage_log entries including model, operation, tokens, cost, quality_outcome, and latency
5. THE Event_Collector SHALL ingest billing events from the billing_events table including subscription state changes, payment successes, and payment failures
6. THE Unified_Event model SHALL support querying by: time range, entity_type, entity_id, source, severity, and event_type
7. THE Event_Collector SHALL process new events within 60 seconds of their occurrence in the source system
8. IF the Event_Collector fails to normalize an event due to missing required fields, THEN THE Event_Collector SHALL store the raw event in a dead-letter queue with the parsing error for manual review

### Requirement 4: Read-Only Intelligence Layer — Core Constraints

**User Story:** As the Platform Operator, I want absolute guarantee that the AI Agent operates in read-only mode, so that it cannot accidentally modify data or trigger actions.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL operate exclusively using read-only database connections that lack INSERT, UPDATE, DELETE, and DDL privileges on all application tables except its own internal state tables (unified_events, business_incidents, daily_reports, agent_state)
2. THE RAMP_AI_Agent SHALL NOT invoke any Celery task that modifies system state (posting, generation, pipeline triggers, avatar freeze/unfreeze, settings changes)
3. THE RAMP_AI_Agent SHALL NOT call any external API that performs write operations (Reddit API posting, Stripe mutations, Brevo email sending for client communications)
4. THE RAMP_AI_Agent SHALL NOT modify any system_settings values, feature flags, or kill switches
5. IF a code path within RAMP_AI_Agent attempts a write operation on a protected table, THEN the database connection SHALL reject the operation and the RAMP_AI_Agent SHALL log the rejected attempt as a safety violation
6. THE RAMP_AI_Agent SHALL write only to its own designated tables: unified_events, business_incidents, daily_reports, agent_analysis_cache, and agent_state

### Requirement 5: Deviation Detection — Happy Path Correlation

**User Story:** As the Platform Operator, I want the AI Agent to automatically detect when real system behavior deviates from the expected Happy Path, so that I am informed about problems before clients notice them.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL continuously compare collected Unified_Events against the Business_Process_Map to identify entities (users, clients, avatars) that have deviated from their expected Happy Path
2. WHEN an entity remains in a non-terminal state longer than the maximum time constraint defined in the Business_Process_Map, THE RAMP_AI_Agent SHALL create a Deviation record with: entity reference, process name, stuck state, expected next state, time exceeded, and probable cause category
3. WHEN an entity experiences a state transition not listed as "allowed" in the Business_Process_Map, THE RAMP_AI_Agent SHALL create a Deviation record with: entity reference, process name, actual transition, expected transitions, and timestamp
4. THE RAMP_AI_Agent SHALL assess each Deviation for client impact using: number of affected end-users, business process criticality (signup/billing are critical; report generation is high; activation is medium), and duration of the deviation
5. THE RAMP_AI_Agent SHALL determine probable cause for each Deviation by correlating with recent error events, infrastructure signals, and external API status within a 30-minute window preceding the deviation
6. THE RAMP_AI_Agent SHALL aggregate multiple related Deviations affecting the same root cause into a single Business_Incident to avoid alert noise

### Requirement 6: Scenario 1 — Customer Success Risk Detection

**User Story:** As the Platform Operator, I want the AI Agent to detect when a user did not receive expected value (registered but didn't activate), so that I can intervene before they churn.

#### Acceptance Criteria

1. THE Scenario_Analyzer SHALL identify users who completed registration but have not verified their email within 48 hours, and create a Business_Incident with type "customer_success_risk" and sub_type "verification_stall"
2. THE Scenario_Analyzer SHALL identify users who started onboarding (completed at least 1 wizard step) but have not progressed for more than 72 hours, and create a Business_Incident with type "customer_success_risk" and sub_type "onboarding_stall"
3. THE Scenario_Analyzer SHALL identify clients who completed onboarding but received zero generated drafts within 7 days, and create a Business_Incident with type "customer_success_risk" and sub_type "no_value_delivered"
4. THE Scenario_Analyzer SHALL identify clients who have generated drafts but zero posted comments within 14 days of first draft, and create a Business_Incident with type "customer_success_risk" and sub_type "activation_failure"
5. FOR EACH customer success risk incident, THE Scenario_Analyzer SHALL determine: which client is affected, at which stage the process stopped, the probable cause (pipeline disabled, avatar frozen, no approved drafts, executor not configured, trial expired), and a recommended action for the operator
6. THE Scenario_Analyzer SHALL evaluate customer success risk conditions at least once every 4 hours
7. THE Scenario_Analyzer SHALL NOT create duplicate incidents for the same client and sub_type combination within a 24-hour window

### Requirement 7: Scenario 2 — AI Reliability Monitoring

**User Story:** As the Platform Operator, I want the AI Agent to monitor LLM operation reliability and detect degradation patterns, so that I can respond before pipeline quality drops.

#### Acceptance Criteria

1. THE Scenario_Analyzer SHALL track LLM reliability metrics per model and operation over a rolling 4-hour window: timeout count, invalid JSON response count, retry count, API error count (4xx and 5xx), and average latency in milliseconds
2. WHEN the timeout rate for any model exceeds 10% of total calls in a 4-hour window (minimum 10 calls), THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_reliability" and sub_type "timeout_spike"
3. WHEN the invalid JSON rate for any model exceeds 15% of total calls in a 4-hour window (minimum 10 calls), THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_reliability" and sub_type "parse_failure_spike"
4. WHEN the retry rate exceeds 30% of total calls in a 4-hour window (minimum 10 calls), THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_reliability" and sub_type "excessive_retries"
5. WHEN the average latency for any model increases by more than 100% compared to its 7-day baseline average (minimum 50 baseline calls), THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_reliability" and sub_type "latency_degradation"
6. FOR EACH AI reliability incident, THE Scenario_Analyzer SHALL include: affected model name, affected operation type, current metric value, baseline metric value, deviation percentage, estimated pipeline impact (drafts affected), and recommended action
7. THE Scenario_Analyzer SHALL evaluate AI reliability conditions at least once every hour

### Requirement 8: Scenario 3 — AI FinOps Anomaly Detection

**User Story:** As the Platform Operator, I want the AI Agent to detect anomalous AI spending patterns, so that I can prevent budget overruns and optimize unit economics.

#### Acceptance Criteria

1. THE Scenario_Analyzer SHALL track AI cost metrics: cost per client per day, cost per operation type per day, retry cost (cost attributed to retry calls), and total daily spend versus 7-day rolling average
2. WHEN a single client's daily AI cost exceeds 3 times the average cost per client for that day, THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_finops" and sub_type "client_cost_outlier"
3. WHEN total daily AI spend exceeds 150% of the 7-day rolling average daily spend, THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_finops" and sub_type "daily_cost_spike"
4. WHEN the retry cost (sum of cost_usd for calls where the same operation+entity combination appears more than once within 5 minutes) exceeds 20% of total daily cost, THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_finops" and sub_type "retry_cost_waste"
5. WHEN the cost per generated draft exceeds $0.30 over a 24-hour period (calculated as total generation cost divided by drafts successfully created), THE Scenario_Analyzer SHALL create a Business_Incident with type "ai_finops" and sub_type "unit_economics_degradation"
6. FOR EACH AI FinOps incident, THE Scenario_Analyzer SHALL include: total cost in the anomaly period, expected cost (baseline), excess cost, breakdown by model and operation, affected clients (if applicable), and recommended action
7. THE Scenario_Analyzer SHALL evaluate AI FinOps conditions once daily at 02:00 Asia/Jerusalem (after daily cost reconciliation completes)

### Requirement 9: Business Incident Model

**User Story:** As the Platform Operator, I want technical events aggregated into a small number of understandable business incidents, so that I can focus on business impact rather than parsing raw technical data.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL store each Business_Incident with fields: id (UUID), type (customer_success_risk, ai_reliability, ai_finops, process_deviation), sub_type (specific scenario identifier), created_at (UTC timestamp), affected_entity_type, affected_entity_id, affected_clients (list of client IDs impacted), severity (low, medium, high, critical), status (open, acknowledged, resolved, false_positive), summary (one-sentence human-readable description), details (JSONB with full context), probable_cause (text), recommended_action (text), and related_events (list of Unified_Event IDs)
2. THE RAMP_AI_Agent SHALL assign severity to each incident based on: critical (billing failure, complete pipeline stop for any client), high (client not receiving value for more than 48 hours, cost spike more than 300%), medium (degradation that may impact client within 24 hours), low (anomaly detected but no immediate client impact)
3. THE RAMP_AI_Agent SHALL aggregate related incidents: multiple technical deviations with the same probable cause within a 1-hour window SHALL be merged into a single Business_Incident with all affected entities listed
4. THE RAMP_AI_Agent SHALL limit incident creation to a maximum of 20 open incidents at any time, prioritizing by severity and recency when the limit is approached
5. WHEN a Business_Incident's underlying condition is no longer detected for 24 hours, THE RAMP_AI_Agent SHALL automatically update the incident status to "resolved"

### Requirement 10: Daily Management Report

**User Story:** As the Platform Operator, I want a brief daily report summarizing the most significant business incidents, so that I can understand platform health in 2 minutes without a dashboard.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL generate a Daily_Report once per day at 08:30 Asia/Jerusalem containing: report date, overall system health verdict (healthy, degraded, critical), total incident count by severity, and a prioritized list of the top 5 most significant incidents from the past 24 hours
2. FOR EACH incident in the Daily_Report, THE RAMP_AI_Agent SHALL present: what happened (one sentence), which process was affected, which clients were impacted (count and names), probable cause, priority (P1-P4), and recommended action for the operator
3. THE Daily_Report SHALL include an AI cost summary section showing: total spend in the past 24 hours, comparison to 7-day average, top 3 cost-driving operations, and any FinOps incidents
4. THE Daily_Report SHALL include a customer health section showing: total active clients, clients with zero drafts in past 48 hours, clients with stalled onboarding, and trial clients approaching expiration (less than 3 days remaining)
5. THE Daily_Report SHALL be stored in the database as an immutable record and accessible via the admin panel at a dedicated route
6. THE Daily_Report SHALL limit content to a maximum of 1000 words to ensure it remains a brief management summary
7. WHEN no significant incidents occurred in the past 24 hours, THE Daily_Report SHALL state "No significant incidents. All processes operating within normal parameters." with a summary of key metrics (drafts generated, comments posted, AI cost)

### Requirement 11: Extensible Architecture — Data Source Adapters

**User Story:** As the Platform Operator, I want the AI Agent architecture to support adding new data sources (CloudWatch, AWS RDS, SQS, Lambda metrics) without rewriting the system, so that the agent can evolve with infrastructure changes.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL define a DataSourceAdapter interface with methods: connect(), health_check(), fetch_events(since: datetime) → list[RawEvent], and get_metadata() → DataSourceInfo
2. THE Event_Collector SHALL discover and load DataSourceAdapter implementations at startup without requiring changes to the core event processing pipeline
3. WHEN a new DataSourceAdapter is registered, THE Event_Collector SHALL automatically begin ingesting events from that source using the adapter's fetch_events method at the adapter's declared polling interval
4. THE DataSourceAdapter interface SHALL support both pull-based adapters (periodic polling) and push-based adapters (webhook receivers) through a common event output format
5. THE RAMP_AI_Agent SHALL include adapters for the current stack: PostgresAdapter (queries application tables), CeleryEventAdapter (monitors Celery event bus), RedisAdapter (reads heartbeats, counters, lock state), and LLMUsageAdapter (reads ai_usage_log)
6. THE architecture SHALL allow adding future adapters for: CloudWatch metrics, AWS RDS Performance Insights, SQS queue metrics, and Lambda invocation logs, requiring only the new adapter file and a registration entry

### Requirement 12: Extensible Architecture — Scenario Plugin System

**User Story:** As the Platform Operator, I want new analysis scenarios to be addable as independent modules without modifying the core agent, so that the intelligence layer can grow incrementally.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL define a ScenarioPlugin interface with methods: get_name() → str, get_schedule() → CronExpression, evaluate(events: list[Unified_Event], process_map: BusinessProcessMap) → list[Business_Incident], and get_required_event_types() → list[str]
2. THE Scenario_Analyzer SHALL discover and execute all registered ScenarioPlugin implementations according to their declared schedule
3. WHEN a ScenarioPlugin is added to the plugins directory, THE Scenario_Analyzer SHALL load and activate the plugin at the next system restart without requiring changes to the core agent code
4. THE ScenarioPlugin interface SHALL provide access to: historical Unified_Events within a configurable lookback window, the current Business_Process_Map, existing open Business_Incidents (to avoid duplicates), and a method to create new Business_Incidents
5. THE RAMP_AI_Agent SHALL include the three base scenario plugins (Customer Success Risk, AI Reliability, AI FinOps) as reference implementations of the ScenarioPlugin interface
6. IF a ScenarioPlugin raises an unhandled exception during evaluation, THEN THE Scenario_Analyzer SHALL log the error, skip that plugin for the current cycle, and continue executing remaining plugins

### Requirement 13: Agent State Persistence and Observability

**User Story:** As the Platform Operator, I want to see the AI Agent's internal state (what it's tracking, what incidents are open, when it last ran), so that I can verify the agent is functioning correctly.

#### Acceptance Criteria

1. THE RAMP_AI_Agent SHALL persist its operational state including: last successful collection timestamp per data source, list of open Business_Incidents with current status, last Daily_Report generation timestamp, per-scenario last evaluation timestamp, and event processing watermarks (last processed event ID per source)
2. THE RAMP_AI_Agent SHALL expose an admin page at /admin/ai-agent showing: agent health status (running, degraded, stopped), last heartbeat timestamp, open incidents count by type and severity, data source freshness indicators, and next scheduled evaluation times per scenario
3. THE RAMP_AI_Agent SHALL emit a heartbeat event every 60 seconds to confirm the agent process is alive and processing events
4. IF the RAMP_AI_Agent heartbeat is not recorded for 5 minutes, THEN the existing external watchdog SHALL include an alert indicating the AI Agent process is unresponsive
5. THE RAMP_AI_Agent SHALL log every scenario evaluation with: start time, end time, events analyzed count, incidents created count, and any errors encountered
