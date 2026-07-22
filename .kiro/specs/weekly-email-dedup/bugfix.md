# Bugfix Requirements Document

## Introduction

The Weekly System Health email (`send_weekly_system_health_email`) is being sent multiple times in a single week, producing contradictory reports (one showing "0 posted, $12.74 AI cost, generation up 179% WoW" and another showing "24 posted, $1.10 AI cost, generation dropped 86% WoW"). This is caused by a lack of deduplication in the Celery task — Beat catch-up after container restarts or deploys re-fires the crontab entry, and since the task has no idempotency guard, it executes again. The two sends collect data at slightly different times (DB state may change between them), resulting in contradictory metrics. This same pattern was previously fixed for the EPG build task (June 25, 2026) but was never applied to weekly email tasks.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a deploy or container restart causes Celery Beat to catch up on missed schedules THEN the system sends the `send_weekly_system_health_email` task multiple times for the same week

1.2 WHEN `send_weekly_system_health_email` fires multiple times within the same week THEN the system sends multiple emails to the owner with contradictory data (e.g., "0 posted" vs "24 posted", "+179% WoW" vs "-86% WoW")

1.3 WHEN the task fails and triggers `max_retries=1` retry AND Beat catch-up also re-fires the same task THEN the system may send up to 3 emails for the same reporting period (original + retry + catch-up)

1.4 WHEN two task executions query `_collect_system_health_data()` seconds or minutes apart THEN the system produces inconsistent metrics because the underlying data (comment_drafts, ai_usage_log) is being written to concurrently

### Expected Behavior (Correct)

2.1 WHEN `send_weekly_system_health_email` has already been successfully sent for the current week THEN the system SHALL skip execution and return early without sending another email

2.2 WHEN a deploy or container restart triggers Beat catch-up THEN the system SHALL detect that the weekly email was already sent and SHALL NOT send a duplicate

2.3 WHEN the task fires multiple times within a 24-hour window THEN the system SHALL send at most ONE email per reporting period (one calendar week)

2.4 WHEN the deduplication check determines an email was already sent THEN the system SHALL log this as an informational message and return a status indicating the skip reason

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `send_weekly_system_health_email` fires at its scheduled time (Sunday 19:00) and no email has been sent for the current week THEN the system SHALL CONTINUE TO collect system health data and send the report normally

3.2 WHEN `send_weekly_system_health_email` fails with an exception and no email was successfully sent for the current week THEN the system SHALL CONTINUE TO retry (max_retries=1, countdown=300) and send the email on retry success

3.3 WHEN `send_weekly_business_summary_email` fires at its scheduled time (Sunday 19:15) THEN the system SHALL CONTINUE TO send the business summary independently of the system health email dedup logic

3.4 WHEN the system health report is successfully sent THEN the system SHALL CONTINUE TO include all metrics (capacity, latency, pipeline WoW, AI cost WoW, predictions, alerts) with accurate data

3.5 WHEN no owner-role users exist (no recipients) THEN the system SHALL CONTINUE TO return `{"status": "no_recipients"}` without error

---

## Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type WeeklyEmailTaskInvocation
  OUTPUT: boolean
  
  // Returns true when the task fires for a week where an email was already sent
  RETURN X.week_already_sent = true
END FUNCTION
```

## Property: Fix Checking

```pascal
// Property: Fix Checking — Deduplication Guard
FOR ALL X WHERE isBugCondition(X) DO
  result ← send_weekly_system_health_email'(X)
  ASSERT result.status = "already_sent" AND emails_sent_count(X.week) = 1
END FOR
```

## Property: Preservation Checking

```pascal
// Property: Preservation — Normal weekly send unaffected
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
  // i.e., when no email was sent for the current week, behavior is identical
END FOR
```
