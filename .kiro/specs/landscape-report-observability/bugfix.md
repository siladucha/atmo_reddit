# Bugfix Requirements Document

## Introduction

The Landscape Report generation (`app/services/onboarding/landscape_report.py`) has critical observability and delivery gaps. When a report is generated during onboarding or viewed from the client portal, the operation is completely opaque: no execution tracking, no AI cost logging infrastructure, no client-facing status, and silent failure when JSON doesn't parse or load. This makes debugging impossible and leaves clients in a "nothing happened" state on failure. The fix introduces a Report Generation Job entity with full lifecycle tracking, AI cost logging hooks, client-facing status, and JSON validation before publish.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a Landscape Report is generated during onboarding or portal page load THEN the system produces no log of when generation started, which step is executing, where a failure occurred, or how long each step took

1.2 WHEN the Landscape Report generation involves LLM calls (planned `sample_drafts` phase or any future AI enrichment) THEN the system does not log model usage, input/output tokens, cost per call, or total report cost — violating the AI cost centralization invariant

1.3 WHEN a client navigates to the Landscape Report page and generation is still in progress or has failed THEN the system shows either a broken page or stale/empty content with no status indication

1.4 WHEN the Landscape Report generation completes on the backend but the resulting JSON is malformed, fails schema validation, or fails to persist THEN the client sees nothing — the system silently swallows the failure with no error status communicated

1.5 WHEN a report generation fails midway (DB error, timeout, malformed data) THEN there is no job record to identify the failure cause, making QA reproduction and debugging impossible

1.6 WHEN multiple report generations are triggered (page refresh, retry, concurrent requests) THEN the system has no deduplication or lifecycle state — each request starts fresh with no awareness of prior attempts

### Expected Behavior (Correct)

2.1 WHEN a Landscape Report generation is initiated THEN the system SHALL create a Report Generation Job entity with a unique job_id, record the start timestamp, and emit a REPORT_STARTED lifecycle event with structured log data

2.2 WHEN the report generation makes any LLM call THEN the system SHALL use `call_llm()`/`call_llm_json()` from `app.services.ai` and call `log_ai_usage()` with operation name, recording model, input_tokens, output_tokens, cost_usd, and associating the cost with the job_id

2.3 WHEN a client views the Landscape Report page THEN the system SHALL display the current job status: "Generating..." (pending/processing), "Report Ready" (completed), or "Generation failed" (failed) — derived from the job entity lifecycle state

2.4 WHEN the AI response is received THEN the system SHALL parse the JSON, validate it against the expected schema, and only mark the job as completed after successful validation and persistence — if validation fails, the system SHALL mark the job as failed with reason `json_validation_failed` and emit a JSON_VALIDATION_FAILED event

2.5 WHEN a report generation fails at any step THEN the system SHALL record the failure reason, the step that failed, and the timestamp in the job entity, emit a REPORT_FAILED lifecycle event, and make this information queryable by job_id for QA debugging

2.6 WHEN a report generation job already exists in `pending` or `processing` state for a given client THEN the system SHALL NOT create a duplicate job — instead it SHALL return the existing job_id and its current status

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the landscape report generates successfully (happy path with threads found, keywords matched, competitors detected) THEN the system SHALL CONTINUE TO return the same report structure (subreddits_monitored, threads_found, competitor_mentions, high_intent_threads, brand_absent_threads, share_of_voice)

3.2 WHEN a client has no subreddits configured or no threads exist THEN the system SHALL CONTINUE TO return an empty/minimal report without crashing (graceful degradation)

3.3 WHEN the report is accessed from the client portal (`/clients/{id}/landscape`) THEN the system SHALL CONTINUE TO render the landscape template with report data available in the template context

3.4 WHEN the system settings kill switches (pipeline_enabled, etc.) are toggled THEN the Landscape Report generation SHALL CONTINUE TO function independently — it is not gated by pipeline kill switches

3.5 WHEN existing onboarding flow triggers report generation THEN the system SHALL CONTINUE TO generate the report inline (synchronous for MVP) without requiring the client to take additional action
