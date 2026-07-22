# Requirements Document

## Introduction

Engineering Memory / QA Intelligence Layer 0 — a structured process for transforming system problems into organizational knowledge. The goal is NOT a bug tracker. The goal is a memory and improvement mechanism where every incident leaves the system stronger: Understanding the cause → Fix → New rule → Protection from repetition.

**Core Principle: Engineering Memory is the primary product of Layer 0.** Intake forms, views, and integrations exist only to populate and use this memory. Without the memory loop working end-to-end, nothing else has value.

MVP implementation uses Notion as the database (external tool), with Notion MCP as the engineer AI access interface. The system serves four roles: Client (problem reporter), QA/Jenny (lifecycle manager), Engineer (knowledge consumer/contributor), and Product Owner/Tzvi (visibility consumer).

## Glossary

- **Engineering_Memory_Database**: A Notion database containing structured records of all system problems, their root causes, fixes, rules, and protections
- **Incident**: A single record in the Engineering Memory Database representing one system problem and its full resolution lifecycle
- **Rule**: A preventive guideline derived from the root cause analysis of a resolved incident, describing how to avoid repetition
- **Protection**: The enforcement mechanism for a Rule (CI check, test, prompt constraint, checklist item, or manual review process)
- **Intake_Form**: A client-facing form for reporting system problems without requiring technical knowledge
- **Incident_Lifecycle**: The four-stage process an incident follows: Reported → Investigating → Fixed → Verified
- **Root_Cause**: The underlying reason why a problem occurred, identified during investigation
- **Category**: The system domain an incident belongs to (AI, UX, Backend, Compliance, or Integration)
- **Protection_Type**: The enforcement class for a rule (None / Manual / Test / CI / Prompt / Checklist). "None" explicitly means accepted risk — a valid engineering decision
- **Risk_Level**: The business/safety risk level of an incident (Low / Medium / High / Critical), distinct from severity — measures potential impact on platform integrity, not bug importance
- **Notion_MCP**: The Model Context Protocol interface enabling AI tools to query, search, and create records in the Engineering Memory Database
- **QA_Operator**: The person (Jenny) responsible for managing incident lifecycle, verification, and database hygiene
- **Engineer_AI_Interface**: The conversational access point through which engineers interact with the Engineering Memory Database via Notion MCP

## Requirements

### Requirement 1: Engineering Memory Database Schema

**User Story:** As an engineer, I want a structured database with consistent fields for every incident, so that I can quickly find relevant history and ensure no critical information is lost.

#### Acceptance Criteria

1. THE Engineering_Memory_Database SHALL contain the following fields per Incident: ID (auto-generated unique number), Title (text), Problem (text), Root_Cause (text), Fix (text), Rule (text), Protection (select: None / Manual / Test / CI / Prompt / Checklist), Risk_Level (select: Low / Medium / High / Critical), Category (select: AI / UX / Backend / Compliance / Integration), Status (select: Reported / Investigating / Fixed / Verified), Reporter (text), Date (date), Source (URL or text for logs, PRs, screenshots), and Audit_Reference (text for related audit log entries)
2. WHEN a new Incident is created, THE Engineering_Memory_Database SHALL assign a unique sequential ID automatically, and SHALL block Incident creation until ID assignment succeeds
3. WHEN an Incident has Status equal to Reported, THE Engineering_Memory_Database SHALL require only Title, Problem, Reporter, Date, and Category fields to be populated, and SHALL allow status transitions even when required fields for the current status are incomplete
4. WHEN an Incident transitions to Status Verified, THE Engineering_Memory_Database SHALL require Rule and Protection fields to be populated

### Requirement 2: Client Intake Form

**User Story:** As a client, I want a simple form to report problems without needing technical knowledge, so that issues are captured immediately and enter the resolution pipeline.

#### Acceptance Criteria

1. THE Intake_Form SHALL present the following fields to the client: "What happened?" (required text), "Where did it happen?" (required text), "What was expected?" (required text), "What was the result?" (required text), "Screenshot" (optional file upload), and "Email" (optional text)
2. WHEN a client submits the Intake_Form, THE System SHALL create a new Incident in the Engineering_Memory_Database with Status equal to Reported and Category left empty for QA assignment
3. WHEN a client submits the Intake_Form, THE System SHALL populate the Incident Title from the "What happened?" field (truncated to first sentence if longer than 100 characters), Problem from a concatenation of all four required text fields, Reporter from the Email field or "Client" when Email is not provided, and Date from the submission timestamp
4. THE Intake_Form SHALL display a confirmation message to the client after successful submission
5. THE QA_Operator SHALL assign Category manually after reviewing the reported Incident, as automatic keyword-based categorization is unreliable for non-technical reporters

### Requirement 3: Incident Lifecycle Management

**User Story:** As a QA operator, I want to manage the full lifecycle of each incident from report to verification, so that every problem is tracked through resolution and no incident is left unresolved.

#### Acceptance Criteria

1. THE Engineering_Memory_Database SHALL enforce the following status transitions: Reported → Investigating, Investigating → Fixed, and Fixed → Verified
2. WHEN an Incident transitions from Investigating to Fixed, THE QA_Operator SHALL populate the Root_Cause and Fix fields, and the system SHALL allow this transition even when the problem still reproduces
3. WHEN an Incident transitions from Fixed to Verified, THE QA_Operator SHALL confirm that the problem no longer reproduces, populate the Rule field, and populate the Protection field, and THE System SHALL prevent verification when the problem still reproduces regardless of documentation completeness
4. THE Engineering_Memory_Database SHALL provide a filtered view showing all Incidents grouped by Status, so that the QA_Operator can see investigation progress at a glance
5. IF an Incident remains in Investigating status for more than 7 days, THE Engineering_Memory_Database SHALL mark that Incident with a visual indicator signaling attention is needed

### Requirement 4: Engineer AI Access via Notion MCP

**User Story:** As an engineer, I want to query the Engineering Memory Database through my AI tool using natural language, so that I can find similar problems, view existing rules, and add new incidents without leaving my development environment.

#### Acceptance Criteria

1. WHEN an engineer queries for similar problems, THE Engineer_AI_Interface SHALL search the Engineering_Memory_Database across Title, Problem, Root_Cause, and Rule fields and return matching Incidents
2. WHEN an engineer queries for existing rules by category or keyword, THE Engineer_AI_Interface SHALL return only Incidents with Status Verified that match the query, displaying Rule and Protection fields, and SHALL return an empty result when no Verified Incidents match rather than including unverified Incidents
3. WHEN an engineer requests to add a new incident, THE Engineer_AI_Interface SHALL create a new Incident in the Engineering_Memory_Database with the provided fields and Status equal to Reported
4. THE Engineer_AI_Interface SHALL support knowledge operations via natural language queries such as "Were there terminology issues?", "What risks exist when changing the comment generator?", "What limitations exist for Reddit publishing?", and "Add a new incident after this fix"
5. THE Engineer_AI_Interface SHALL operate as a knowledge interface (search, read, add) rather than a generic CRUD tool — engineers interact with engineering memory, not with database pages

### Requirement 5: Product Owner Visibility

**User Story:** As a product owner, I want to see what problems exist, what has been fixed, and what system improvements have been created, so that I can track system health evolution without reading technical details.

#### Acceptance Criteria

1. THE Engineering_Memory_Database SHALL provide a summary view showing counts of Incidents by Status (Reported, Investigating, Fixed, Verified)
2. THE Engineering_Memory_Database SHALL provide a view of recently Verified Incidents displaying Title, Category, Rule, and Protection fields
3. THE Engineering_Memory_Database SHALL provide a view of currently open Incidents (Status not equal to Verified) sorted by Date descending

### Requirement 6: Initial Seed Data

**User Story:** As a QA operator, I want the database pre-populated with at least 5 real historical RAMP incidents, so that the system has working examples demonstrating the complete lifecycle and engineers can immediately reference past solutions.

#### Acceptance Criteria

1. THE Engineering_Memory_Database SHALL contain at least 5 Incidents with Status Verified upon initial deployment
2. WHEN initial seed data is entered, THE Incidents SHALL cover at least 3 different Categories
3. WHEN initial seed data is entered, THE Incidents SHALL include at least one actual database record from each of: public terminology issue, conflicting weekly reports, audit log issue, client UX issue, and AI behavior issue
4. WHEN initial seed data is entered, each Incident SHALL have all fields populated including Rule and Protection

### Requirement 7: Closed Incident Completeness

**User Story:** As an engineer, I want every closed (Verified) incident to contain a Rule and Protection, so that the Engineering Memory Database serves as a living rulebook preventing problem repetition.

#### Acceptance Criteria

1. THE Engineering_Memory_Database SHALL NOT allow an Incident to transition to Status Verified when the Rule field is empty, enforced only during active transition attempts
2. THE Engineering_Memory_Database SHALL NOT allow an Incident to transition to Status Verified when the Protection field is empty, enforced only during active transition attempts
3. WHEN an engineer consults the Engineering_Memory_Database before making changes, THE Engineer_AI_Interface SHALL return applicable Rules from Verified Incidents that match the area of the codebase being modified


### Requirement 8: Learning Loop End-to-End Validation

**User Story:** As a product owner, I want proof that the Engineering Memory actually functions as a learning loop (not just a task list), so that we can confirm Layer 0 is validated before investing in further automation.

#### Acceptance Criteria

1. THE System SHALL demonstrate the following end-to-end scenario: QA creates a problem → Engineer investigates and fixes → Engineer creates Rule + Protection → A different engineer (or the same engineer in a new context) queries "What constraints exist for [area]?" → THE Engineer_AI_Interface returns the previously created Rule
2. WHEN the Learning Loop scenario is completed successfully, THE System SHALL be considered validated for Layer 0 — proving that experience transforms into retrievable system constraints
3. THE Learning Loop test SHALL be documented as the primary acceptance test for Layer 0 MVP completion, taking precedence over individual component tests
