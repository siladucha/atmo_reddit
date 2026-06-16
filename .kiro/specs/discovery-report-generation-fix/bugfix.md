# Bugfix Requirements Document

## Introduction

The Discovery Engine's "Generate Report" button fails to appear after the research phase completes via HTMX polling. When the `GET /{session_id}/progress` endpoint detects that all hypotheses have been researched (`all_done = True`), it transitions the UI from the research progress partial to the results partial (`discovery_results.html`). However, it does not pass the `can_generate_report` or `is_max_iterations` template context variables. Since Jinja2 treats undefined variables as falsy, the "Generate Report" button is never rendered — making it impossible for operators to generate the Visibility Report through the normal HTMX-driven workflow.

This bug affects all Discovery sessions that complete research via background Celery tasks and poll via HTMX, which is the standard flow for every session.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the research progress endpoint (`GET /admin/discovery/{session_id}/progress`) detects all hypotheses are researched and renders `discovery_results.html` THEN the system does not pass `can_generate_report` to the template context, causing the "Generate Report" button to never appear

1.2 WHEN the research progress endpoint renders `discovery_results.html` after research completion THEN the system does not pass `is_max_iterations` to the template context, causing the "Next Iteration" button logic to malfunction (always showing the button regardless of iteration count)

1.3 WHEN the operator refreshes the session page manually (full page load) after research is complete and all hypotheses are decided THEN the system correctly shows the "Generate Report" button (because the session page route passes all required context variables)

### Expected Behavior (Correct)

2.1 WHEN the research progress endpoint detects all hypotheses are researched and renders `discovery_results.html` THEN the system SHALL pass `can_generate_report` (computed from `SessionManager.can_generate_report(session)`) to the template context so the "Generate Report" button appears when conditions are met

2.2 WHEN the research progress endpoint renders `discovery_results.html` after research completion THEN the system SHALL pass `is_max_iterations` (computed from `SessionManager.is_at_max_iterations(session)`) to the template context so the iteration controls render correctly

2.3 WHEN at least one hypothesis is confirmed and research is complete THEN the system SHALL display the "Generate Report" button in the results partial regardless of whether the partial was loaded via HTMX polling or full page load

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the `decide_hypotheses` endpoint (`POST /admin/discovery/{session_id}/decide`) renders `discovery_results.html` THEN the system SHALL CONTINUE TO pass `can_generate_report` and `is_max_iterations` to the template context as it currently does

3.2 WHEN the session page route (`GET /admin/discovery/{session_id}`) renders the full page with `current_step == "results"` THEN the system SHALL CONTINUE TO pass `can_generate_report` and `is_max_iterations` to the template context as it currently does

3.3 WHEN research is still in progress (not all hypotheses complete) THEN the progress endpoint SHALL CONTINUE TO return the `discovery_research_progress.html` partial for HTMX polling

3.4 WHEN the `generate_report` endpoint (`POST /admin/discovery/{session_id}/report`) is called THEN the system SHALL CONTINUE TO validate that `can_generate_report` is true before proceeding with LLM report generation
