# Bugfix Requirements Document

## Introduction

When emotional profile analysis fails for a subreddit (due to PRAW errors, insufficient comments, non-existent subreddit, or LLM failures), the system stores the error in `subreddit.emotional_profile_error` but the UI never displays it. Users click "Run Analysis", wait, refresh, and see only "Not yet analyzed" — with zero indication of what went wrong. This affects both admin users on the subreddit detail page and client portal users viewing the Community Tone section on the subreddit risk profile page.

A partial fix has been applied to the admin-side GET handler (`admin_get_emotional_profile_partial`) which now renders the error. This spec captures the full bug condition and ensures all user-facing surfaces provide appropriate feedback.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN emotional profile analysis fails (PRAW error, insufficient comments, LLM error, or schema validation failure) AND a client portal user views the subreddit risk profile page THEN the system shows "Community tone analysis pending" with no indication that analysis was attempted and failed

1.2 WHEN the POST handler dispatches a Celery task for a subreddit that exists in the DB but cannot be reached on Reddit (e.g., banned subreddit, private subreddit, PRAW timeout) THEN the system shows "Analysis started... Refresh page in 30-60s" but the user never receives any follow-up feedback about the failure

1.3 WHEN `subreddit.emotional_profile_error` contains a stored error message AND the client portal Community Tone section is rendered THEN the system ignores the error field and displays only the generic "pending" state

### Expected Behavior (Correct)

2.1 WHEN emotional profile analysis has failed AND a client portal user views the subreddit risk profile page THEN the system SHALL display a user-friendly error message indicating that analysis was attempted but did not succeed, along with a general reason (e.g., "not enough community data", "subreddit unreachable", "analysis error")

2.2 WHEN the POST handler dispatches a Celery task THEN the system SHALL provide accurate status feedback indicating that the task is queued and that the user should check back, and if a previous error exists it SHALL be cleared before the new attempt

2.3 WHEN `subreddit.emotional_profile_error` is set on a subreddit record THEN the client portal Community Tone section SHALL render the error state with a human-readable explanation instead of showing the generic "pending" message

### Unchanged Behavior (Regression Prevention)

3.1 WHEN emotional profile analysis succeeds and `subreddit.emotional_profile` contains valid profile data THEN the system SHALL CONTINUE TO display the full emotional profile (formality, humor, expertise, dominant emotions, summary) on both admin and client portal pages

3.2 WHEN a subreddit has never been analyzed (`emotional_profile` is NULL and `emotional_profile_error` is NULL) THEN the system SHALL CONTINUE TO display the "Not yet analyzed" / "pending" state with the "Run Analysis" button on admin pages

3.3 WHEN the admin-side GET handler renders the emotional profile partial THEN the system SHALL CONTINUE TO display the error message (already fixed) and the "Run Analysis" button for retry

3.4 WHEN analysis is triggered via the POST handler and the subreddit does not exist in the DB THEN the system SHALL CONTINUE TO return an immediate inline error without dispatching a Celery task
