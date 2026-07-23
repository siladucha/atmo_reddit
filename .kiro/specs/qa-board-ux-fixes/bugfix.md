# Bugfix Requirements Document

## Introduction

Five UX/functional issues with the Report Issue form (`/report-issue`) and QA Board (`/admin/qa-board`) in RAMP's Engineering Memory system. These bugs reduce usability for reporters (unnecessary required field, no clipboard paste), reduce visibility for QA reviewers (environment not prominent, missing structured fields), and force context-switching (screenshots open in new tab instead of inline modal).

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a reporter submits the report-issue form without filling in the "What was expected?" field THEN the system rejects the submission with a validation error "'Expected?' is required"

1.2 WHEN a QA reviewer views the bug list on the QA Board THEN the environment field (dev/staging/prod) is displayed as plain gray text in the footer line alongside date and reporter, making it difficult to identify which environment an issue relates to

1.3 WHEN a QA reviewer clicks a screenshot thumbnail on the QA Board THEN the system opens the full image in a new browser tab (target="_blank"), forcing the user to leave the QA Board page

1.4 WHEN a bug report is created from the form THEN the "where" field value is concatenated into the "problem" text blob and not stored as a separate structured field, the reporter email is only embedded in the "reporter" string and not separately visible on the QA Board, and the source_url field in the model is never populated from the form

1.5 WHEN a reporter pastes an image from clipboard (Cmd+V / Ctrl+V) on the report-issue form THEN nothing happens because the screenshot input only supports traditional file picker (click to browse)

### Expected Behavior (Correct)

2.1 WHEN a reporter submits the report-issue form without filling in the "What was expected?" field THEN the system SHALL accept the submission successfully (the field is optional — no `required` attribute, no red asterisk, no server-side validation requiring it)

2.2 WHEN a QA reviewer views the bug list on the QA Board THEN the environment SHALL be displayed as a colored badge in the header line alongside bug_id, risk_level, category, and status badges (prod=red background, staging=yellow background, dev=gray background)

2.3 WHEN a QA reviewer clicks a screenshot thumbnail on the QA Board THEN the system SHALL display the full-size image in a modal/lightbox overlay within the page, with a close button and click-outside-to-dismiss behavior, without navigating away from the QA Board

2.4 WHEN a bug report is created from the form THEN the system SHALL store the "where" value as the `source_url` field on the BugReport model, display the reporter email separately on the QA Board (visible in the details section), and show the source_url as a visible field on the QA Board

2.5 WHEN a reporter pastes an image from clipboard (Cmd+V / Ctrl+V) anywhere on the report-issue form THEN the system SHALL capture the pasted image, show a preview thumbnail, and attach it as the screenshot for submission (same as if selected via file picker)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a reporter submits the form with all required fields filled (what_happened, where, actual_result) THEN the system SHALL CONTINUE TO create a BugReport record and show the success confirmation

3.2 WHEN a reporter submits the form THEN the anti-bot protection (honeypot + JS challenge + timing) SHALL CONTINUE TO reject bot submissions silently

3.3 WHEN a QA reviewer views the QA Board THEN the existing badge display for bug_id, risk_level, category, and status SHALL CONTINUE TO render correctly with their current colors and positioning

3.4 WHEN a QA reviewer uses the inline status update form (HTMX) on the QA Board THEN the status change SHALL CONTINUE TO work correctly with the select + comment + update button pattern

3.5 WHEN a reporter uses the traditional file picker to select a screenshot THEN the system SHALL CONTINUE TO upload and attach the file as before

3.6 WHEN accessing the QA Board THEN the platform_admin role requirement SHALL CONTINUE TO be enforced

3.7 WHEN a reporter fills in the "What was expected?" field (now optional) THEN the system SHALL CONTINUE TO include that value in the problem text blob as before
