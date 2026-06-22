#!/usr/bin/env python3
"""Write the detailed requirements.md for production-readiness-audit."""

path = '/Volumes/2SSD/Projects/ReddirSaaS/.kiro/specs/production-readiness-audit/requirements.md'

content = r'''# Requirements Document

## Introduction

Production Readiness Audit is a mandatory Go/No-Go gate before RAMP deploys to production with paying clients. The audit systematically identifies hidden risks across data leakage, credit/usage integrity, rate limiting coverage, LLM response reliability, user flow completeness, specification coverage, and technical debt. The output is a unified risk report with a traffic-light dashboard (RED/YELLOW/GREEN) enabling an objective GO/NO-GO decision.

This is not a bugfix sprint — it is a structured reliability and security audit that produces actionable artifacts: integration maps, state diagrams, flow inventories, and a production dashboard.

## Glossary

- **Audit_Engine**: The system responsible for executing audit checks, collecting findings, and producing reports
- **Data_Path_Analyzer**: The component that traces data flow from external sources through processing to output
- **Credit_Integrity_Checker**: The component that verifies usage accounting state transitions and invariants
- **Rate_Limit_Auditor**: The component that verifies all operations route through the unified rate limit engine
- **LLM_Reliability_Monitor**: The component that tracks LLM task lifecycle states and detects lost responses
- **Flow_Completeness_Scanner**: The component that inventories all user/system flows and verifies terminal states
- **Spec_Coverage_Tracker**: The component that maps specifications to implementation and test coverage
- **Debt_Radar**: The component that scans codebase for reliability, performance, security, and product debt patterns
- **Production_Dashboard**: The admin UI screen displaying the unified RED/YELLOW/GREEN status of all audit findings
- **External_Integration**: Any connection to Reddit API, LLM providers (LiteLLM/Claude/Gemini), or third-party services
- **Bypass_Path**: Any code path that executes an operation without going through the expected control gate (rate limiter, permission check, safety gate)
- **Lost_Response**: An LLM task that was accepted but whose response is neither delivered nor recoverable
- **Flow_Inventory**: A complete catalog of all user and system flows with their terminal states documented
- **Blocker**: A finding with severity RED that prevents production deployment
- **Retention_Policy**: The configured data lifecycle period (90 days for scraped threads, indefinite for audit logs)
- **Idempotency_Key**: A unique identifier ensuring an operation executes exactly once even when retried

## Requirements

### Requirement 1: External Data Leakage Detection

**User Story:** As a platform operator, I want to trace all external data paths end-to-end, so that I can verify no sensitive data leaks beyond its intended boundary.

#### Acceptance Criteria

1. WHEN an audit is initiated, THE Data_Path_Analyzer SHALL trace every external integration path from source fetch through queue, processing, storage, LLM context, to output, covering at minimum: Reddit API (PRAW), LLM providers (LiteLLM/Gemini/Claude), Redis cache, PostgreSQL storage, proxy services, and SSE notification channels
2. THE Data_Path_Analyzer SHALL verify that raw API responses from Reddit are not stored with more than 500 characters of the original post body beyond the retention policy of 90 days, and that any records older than 90 days contain only derived metadata (scores, flags, IDs)
3. THE Data_Path_Analyzer SHALL verify that authentication tokens (Reddit OAuth, LLM API keys, proxy credentials) are not transmitted to any external service other than their intended provider, where intended providers are: Reddit OAuth tokens to reddit.com only, LLM API keys to their respective provider endpoints only, and proxy credentials to the configured proxy host only
4. THE Data_Path_Analyzer SHALL verify that no private user data (passwords, email addresses, IP addresses, OAuth refresh tokens) appears in application logs across all configured log outputs (stdout, file-based logs, and activity_events table free-text fields)
5. THE Data_Path_Analyzer SHALL verify that raw scraped content does not enter embedding vectors without sanitization, where sanitization requires at minimum: removal of usernames, removal of URLs, and stripping of Markdown formatting before vectorization
6. THE Data_Path_Analyzer SHALL verify that cached external data in Redis is purged according to the configured retention policy, and that no cache key containing external API response data has a TTL exceeding 24 hours or persists beyond the configured retention period
7. THE Data_Path_Analyzer SHALL verify that no internal database IDs (primary keys, foreign keys, or UUIDs used as row identifiers) are exposed in user-facing output or API responses to non-admin roles
8. THE Data_Path_Analyzer SHALL verify that LLM prompts do not contain credentials, internal database IDs, or data from other clients (context isolation check), by confirming each prompt includes data from at most one client_id
9. WHEN the trace is complete, THE Data_Path_Analyzer SHALL produce an integration map table with columns: Integration, Data_Read, Data_Stored, Retention_Period, Access_Roles, and Compliance_Status (PASS or FAIL with reason)
10. IF any criterion (2 through 8) detects a violation, THEN THE Data_Path_Analyzer SHALL flag the violation in the integration map with the specific criterion failed, the data path where the violation occurred, and a severity level (critical for credential exposure, high for cross-client leakage, medium for retention violations)
11. IF no retention policy is explicitly configured for a data category, THEN THE Data_Path_Analyzer SHALL apply the default retention limit of 90 days for scraped content and 24 hours for cached API responses
'''

with open(path, 'w') as f:
    f.write(content)
print("Part 1 written")
