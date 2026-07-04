# Requirements Document

## Introduction

This document defines the requirements for a comprehensive penetration testing specification for the RAMP platform (Reddit Attention Management Platform). The penetration test verifies system resilience against external and internal attack vectors, covering unauthorized data access, authorization bypass, plan limit circumvention, API exploitation, AI/agent layer vulnerabilities, and resource abuse. The test scope encompasses the web frontend, public REST API, JWT authentication system, billing/plan enforcement layer, admin panel, AI-agent layer, webhooks/integrations, and database access layer.

## Glossary

- **RAMP**: Reddit Attention Management Platform — the multi-tenant SaaS system under test
- **Pentester**: The security tester executing attack scenarios against RAMP
- **Test_Harness**: The automated testing framework orchestrating penetration test execution and reporting
- **Auth_System**: The JWT-based authentication and session management subsystem (python-jose + passlib)
- **RBAC_Engine**: The Role-Based Access Control enforcement layer with 7 roles (owner, partner, client_admin, client_manager, client_viewer, avatar_manager, b2c_user)
- **Plan_Enforcer**: The billing/plan enforcement layer that restricts features and limits by subscription tier (trial, seed, starter, growth, scale)
- **AI_Agent_Layer**: The LLM integration layer (LiteLLM → call_llm) including prompt assembly, tool calls, and budget gating
- **Tenant_Isolation**: The data separation mechanism ensuring Client A never accesses Client B data (query_scope.py + isolation.py)
- **Rate_Limiter**: The middleware-based request throttling system (5 auth/15min, 100 global/min per IP)
- **Finding**: A discovered vulnerability with assigned severity (Critical, High, Medium, Low)
- **Attack_Surface_Map**: A structured document identifying all externally accessible endpoints, parameters, and data flows
- **IDOR**: Insecure Direct Object Reference — accessing resources by manipulating object identifiers
- **Prompt_Injection**: An attack where user-controlled input manipulates LLM system prompts or tool behavior

## Requirements

### Requirement 1: Reconnaissance and Attack Surface Mapping

**User Story:** As a Pentester, I want to systematically discover all exposed endpoints, schemas, and secrets, so that I can identify the full attack surface before targeted testing begins.

#### Acceptance Criteria

1. WHEN the reconnaissance phase begins, THE Test_Harness SHALL enumerate all public API endpoints by analyzing route definitions, OpenAPI schemas, and JavaScript bundle contents
2. WHEN endpoint enumeration completes, THE Test_Harness SHALL identify webhook callback URLs, integration endpoints (Reddit OAuth, Brevo), and extension API paths
3. WHEN scanning JavaScript bundles served by the frontend, THE Test_Harness SHALL detect any hardcoded secrets, API keys, internal URLs, or debug configuration values
4. WHEN reconnaissance completes, THE Test_Harness SHALL produce an Attack_Surface_Map documenting each discovered endpoint with its HTTP method, authentication requirement, and input parameters
5. IF reconnaissance discovers an endpoint not protected by authentication middleware, THEN THE Test_Harness SHALL flag the endpoint as a Critical or High severity Finding

### Requirement 2: Authentication and Session Security Testing

**User Story:** As a Pentester, I want to verify that the authentication system resists brute-force, token forgery, session fixation, and session invalidation bypass, so that unauthorized parties cannot gain access to user accounts.

#### Acceptance Criteria

1. WHEN testing brute-force resistance, THE Test_Harness SHALL verify that the Rate_Limiter blocks login attempts after 5 failed attempts within 15 minutes per IP address, using Redis-backed shared state across all workers
2. WHEN testing JWT token security, THE Test_Harness SHALL attempt algorithm confusion attacks (alg:none, HS256 vs RS256 substitution) and verify the Auth_System rejects forged tokens
3. WHEN testing JWT expiry enforcement, THE Test_Harness SHALL verify that expired tokens are rejected and cannot be used to access protected resources
4. WHEN testing token tampering, THE Test_Harness SHALL modify JWT payload claims (user_id, role, client_id) and verify the Auth_System rejects tampered tokens
5. WHEN testing session fixation, THE Test_Harness SHALL verify that login generates a new session token and does not accept pre-set session identifiers
6. WHEN testing logout invalidation, THE Test_Harness SHALL verify that after logout the previously issued JWT cookie is removed and the token cannot be reused from another client (NOTE: system uses stateless JWT — no server-side revocation list. This is a known architectural limitation documented as Medium-severity finding)
7. WHEN testing password reset flow, THE Test_Harness SHALL verify that reset tokens are single-use, expire within 1 hour, and cannot be reused after password change
8. WHEN testing email verification flow, THE Test_Harness SHALL verify that verification tokens expire within 48 hours, are single-use, and cannot be enumerated via brute-force
9. WHEN testing long-lived extension tokens, THE Test_Harness SHALL verify that 90-day extension JWT tokens cannot be used to access admin endpoints or escalate privileges beyond extension-scoped operations
10. WHEN testing X-Forwarded-For header trust, THE Test_Harness SHALL verify that spoofed X-Forwarded-For headers from non-proxy IPs do NOT bypass rate limiting (only trusted proxy IPs are honored)

### Requirement 3: Authorization and Privilege Escalation Testing (IDOR/RBAC)

**User Story:** As a Pentester, I want to verify that no user can access resources or perform actions beyond their assigned role and client scope, so that multi-tenant data isolation and RBAC boundaries are enforced.

#### Acceptance Criteria

1. WHEN testing cross-client data access, THE Test_Harness SHALL attempt to access Client B resources (avatars, drafts, threads, settings) using Client A credentials by manipulating object IDs in API requests
2. WHEN testing horizontal privilege escalation, THE Test_Harness SHALL verify that a client_viewer cannot perform client_admin or client_manager actions (approve drafts, modify settings, trigger pipeline)
3. WHEN testing vertical privilege escalation, THE Test_Harness SHALL verify that non-admin roles (client_admin, client_manager) cannot access admin-only endpoints (/admin/*)
4. WHEN testing plan limit bypass, THE Test_Harness SHALL verify that a trial-tier user cannot access paid-tier features (extended avatar limits, unlimited subreddits, higher comment quotas) by manipulating API parameters
5. WHEN testing admin endpoint protection, THE Test_Harness SHALL verify that every /admin/* route requires owner, partner, or avatar_manager role and returns 403 for all other roles
6. WHEN testing tenant_id substitution, THE Test_Harness SHALL attempt to replace client_id values in request bodies and query parameters to access other tenants' data
7. WHEN testing RBAC consistency, THE Test_Harness SHALL verify that all 7 role types have correct permissions across all 16 resource categories defined in the permission matrix
8. WHEN testing avatar_manager data scope, THE Test_Harness SHALL verify that avatar_manager role cannot access or modify client-specific sensitive data (billing, strategy, client settings) despite having admin-panel access for avatar operations
9. WHEN testing extension node token scope, THE Test_Harness SHALL verify that extension JWT tokens (issued via /api/extension/activate) cannot access admin endpoints, client portals, or any functionality beyond the extension API namespace

### Requirement 4: Business Logic Attack Testing

**User Story:** As a Pentester, I want to verify that business rules (plan limits, billing, feature gates) cannot be circumvented through logic manipulation, so that RAMP's revenue model and fairness guarantees hold.

#### Acceptance Criteria

1. WHEN testing max_comments_per_month bypass, THE Test_Harness SHALL verify that the Plan_Enforcer blocks draft approval once the monthly quota is reached, at ALL approval paths: portal approve, admin approve, bulk approve, edit+approve, and auto-approve (autopilot)
2. WHEN testing trial-to-paid feature access, THE Test_Harness SHALL verify that trial users cannot access Growth/Scale tier features by modifying request parameters or replaying requests from paid accounts
3. WHEN testing race conditions on billing, THE Test_Harness SHALL send concurrent requests to trigger actions that consume quota and verify that the system does not allow double-consumption or double-access
4. WHEN testing race conditions on EPG slot creation, THE Test_Harness SHALL send parallel EPG build requests and verify the dedup guard prevents duplicate slot creation (max 2 build attempts per day)
5. WHEN testing client_id substitution in pipeline triggers, THE Test_Harness SHALL verify that triggering a pipeline run with a different client_id does not execute on behalf of the substituted client
6. WHEN testing plan enforcement at generation vs approval, THE Test_Harness SHALL verify that both the soft gate (portfolio_manager budget limit at generation) AND the hard gate (plan_enforcement service at approval) correctly enforce monthly limits
7. IF a business logic bypass is discovered that allows unpaid access to paid features, THEN THE Test_Harness SHALL classify the Finding as Critical severity

### Requirement 5: API Security Testing

**User Story:** As a Pentester, I want to verify that API endpoints resist injection, mass assignment, and excessive data exposure, so that the system is protected against common API attack vectors.

#### Acceptance Criteria

1. WHEN testing for SQL injection, THE Test_Harness SHALL attempt injection payloads in all string-type query parameters, path parameters, and request body fields across all API endpoints
2. WHEN testing for NoSQL injection, THE Test_Harness SHALL attempt JSONB manipulation payloads in fields that accept structured data (keywords JSONB, strategy_context JSONB, activation_route JSONB)
3. WHEN testing for command injection, THE Test_Harness SHALL attempt OS command injection through any parameter that may interact with system processes (webhook URLs, Reddit usernames, subreddit names)
4. WHEN testing for mass assignment, THE Test_Harness SHALL send additional fields (role, is_active, plan_type, is_frozen, client_id) in create/update requests and verify the system ignores unpermitted fields
5. WHEN testing for excessive data exposure, THE Test_Harness SHALL verify that API responses do not include sensitive fields (password hashes, JWT secrets, API keys, verification tokens, reset tokens) in any response payload
6. WHEN testing query parameter injection, THE Test_Harness SHALL attempt to modify pagination, filtering, and sorting parameters to extract data beyond the caller's authorized scope

### Requirement 6: AI/Agent Security Testing

**User Story:** As a Pentester, I want to verify that the AI/agent layer resists prompt injection, data exfiltration via tool calls, and system prompt disclosure, so that LLM interactions cannot be weaponized against the system or its data.

#### Acceptance Criteria

1. WHEN testing prompt injection via user input, THE Test_Harness SHALL inject adversarial prompts through all user-controllable text fields that flow into LLM context (brand_voice, persona_bio, keywords, subreddit names, client strategy fields)
2. WHEN testing data exfiltration via LLM output, THE Test_Harness SHALL verify that injected prompts cannot cause the AI_Agent_Layer to include system instructions, other client data, API keys, or credential fragments in generated comment text visible to users
3. WHEN testing system prompt bypass, THE Test_Harness SHALL attempt to make the AI_Agent_Layer reveal its system prompt, internal instructions, or configuration parameters through crafted user inputs that appear in generated drafts
4. WHEN testing plan limit manipulation via prompts, THE Test_Harness SHALL verify that injected prompts cannot instruct the AI_Agent_Layer to bypass budget gates, ignore phase restrictions, or modify plan limits
5. WHEN testing AI output manipulation, THE Test_Harness SHALL verify that injected prompts cannot cause the AI_Agent_Layer to generate content that violates safety_blocks.py rules (brand mentions in Phase 1/2, promotional language)
6. WHEN testing LLM budget exhaustion, THE Test_Harness SHALL verify that crafted inputs cannot cause excessive token consumption that bypasses the 500/hour or 3000/day budget gate or the $5/10-min cost circuit breaker
7. WHEN testing per-task call counter bypass, THE Test_Harness SHALL verify that no single request or task can make more than 50 LLM calls (per-task ContextVar limit)
8. IF prompt injection results in cross-tenant data leakage via the AI_Agent_Layer, THEN THE Test_Harness SHALL classify the Finding as Critical severity

### Requirement 7: Data Security and Privacy Testing

**User Story:** As a Pentester, I want to verify that PII and sensitive data cannot be accessed through unauthorized channels, so that client and system confidentiality is maintained.

#### Acceptance Criteria

1. WHEN testing for PII leaks in API responses, THE Test_Harness SHALL verify that list endpoints with pagination do not expose data from other tenants through cursor manipulation or offset injection
2. WHEN testing for cross-object access via API fuzzing, THE Test_Harness SHALL send randomized and sequential object IDs to all endpoints that accept resource identifiers and verify Tenant_Isolation prevents unauthorized access
3. WHEN testing for secrets in logs, THE Test_Harness SHALL verify that application logs (accessible via admin endpoints or log files) do not contain JWT tokens, API keys, passwords, or verification/reset tokens in plaintext
4. WHEN testing encrypted field protection, THE Test_Harness SHALL verify that Fernet-encrypted fields (proxy URLs, Reddit passwords, OAuth tokens) are never returned in decrypted form via any API response
5. WHEN testing export endpoints, THE Test_Harness SHALL verify that data export functionality enforces client_id scoping and does not allow cross-tenant data extraction

### Requirement 8: Rate Limiting and Abuse Resistance Testing

**User Story:** As a Pentester, I want to verify that rate limiting and resource controls resist sustained abuse, so that the system remains available under deliberate overload attempts.

#### Acceptance Criteria

1. WHEN testing API spam resistance, THE Test_Harness SHALL verify that the global rate limit (100 requests per 60 seconds per IP) is enforced across all endpoints and returns 429 status when exceeded, using Redis-backed shared counters across all workers
2. WHEN testing auth endpoint abuse, THE Test_Harness SHALL verify that the auth rate limit (5 attempts per 15 minutes per IP) cannot be bypassed through X-Forwarded-For or X-Real-IP header manipulation from non-trusted-proxy source IPs
3. WHEN testing comment/post flooding, THE Test_Harness SHALL verify that the Plan_Enforcer daily caps and per-avatar posting limits cannot be exceeded through concurrent requests
4. WHEN testing endpoint cost exhaustion, THE Test_Harness SHALL identify expensive endpoints (LLM calls, Reddit API proxying, report generation) and verify that repeated calls trigger rate limiting or budget gates before resource exhaustion
5. WHEN testing concurrency stress, THE Test_Harness SHALL send parallel requests to stateful operations (EPG build, pipeline trigger, draft approval) and verify that distributed locks prevent race conditions and resource corruption
6. WHEN testing LLM budget gate bypass, THE Test_Harness SHALL verify that the Redis-based budget counters (500/hour, 3000/day) and the $5/10-min cost circuit breaker cannot be circumvented by request timing, header manipulation, or concurrent calls
7. WHEN testing rate limiter Redis failover, THE Test_Harness SHALL verify that when Redis is unavailable, the in-memory fallback rate limiter still provides per-process protection (degraded but not absent)
8. WHEN testing extension activation abuse, THE Test_Harness SHALL verify that /api/extension/activate is rate-limited (included in auth rate limit paths) and that activation fails for avatars without configured executor_email

### Requirement 9: Infrastructure Security Testing

**User Story:** As a Pentester, I want to verify that HTTP security headers, CORS configuration, and caching behavior prevent common web-layer attacks, so that the application's transport and browser security is sound.

#### Acceptance Criteria

1. WHEN testing security headers, THE Test_Harness SHALL verify the presence and correct values of X-Frame-Options (DENY), X-Content-Type-Options (nosniff), Strict-Transport-Security (HSTS), Referrer-Policy (strict-origin-when-cross-origin), and Permissions-Policy headers on all responses
2. WHEN testing CORS configuration, THE Test_Harness SHALL verify that the Access-Control-Allow-Origin header does not allow arbitrary origins, and that credentials (cookies, authorization headers) are not exposed to unauthorized origins
3. WHEN testing for cache leaks between tenants, THE Test_Harness SHALL verify that CDN or server-side caching does not serve cached responses containing tenant-specific data to other authenticated users
4. WHEN testing CSP (Content Security Policy), THE Test_Harness SHALL verify that inline scripts are restricted and that external script sources are limited to trusted domains
5. IF security headers are missing or misconfigured on any response, THEN THE Test_Harness SHALL classify the Finding as Medium severity

### Requirement 10: Threat Model Role Coverage

**User Story:** As a Pentester, I want to execute all tests from the perspective of each defined threat actor role, so that the penetration test provides complete coverage across attack personas.

#### Acceptance Criteria

1. THE Test_Harness SHALL execute the complete test suite from the perspective of an Anonymous user (no authentication)
2. THE Test_Harness SHALL execute the complete test suite from the perspective of a Free/trial user (expired or active 14-day trial)
3. THE Test_Harness SHALL execute the complete test suite from the perspective of a Paid user across at least two different plan tiers (starter and growth or scale)
4. THE Test_Harness SHALL execute the complete test suite from the perspective of a Compromised user token (valid JWT with tampered claims)
5. THE Test_Harness SHALL execute the complete test suite from the perspective of a Malicious admin (valid owner or partner credentials testing cross-boundary actions in a multi-admin system)
6. WHEN all threat model roles have been tested, THE Test_Harness SHALL produce a coverage matrix mapping each Finding to the threat actor role that discovered the vulnerability

### Requirement 11: Finding Classification and Reporting

**User Story:** As a Pentester, I want a structured classification and reporting framework, so that findings are actionable and prioritized for remediation.

#### Acceptance Criteria

1. THE Test_Harness SHALL classify each Finding into one of four severity levels: Critical (access to other client data, paid feature bypass, impersonation, secrets/API key leaks), High (partial RBAC bypass, AI prompt injection with context leak, significant rate limit abuse), Medium (information disclosure, weak headers, minor logic flaws), Low (UI issues, non-exploitable leaks)
2. FOR EACH Finding, THE Test_Harness SHALL record the reproduction steps, affected endpoint, threat actor role, evidence (request/response), and a suggested remediation
3. WHEN all testing phases complete, THE Test_Harness SHALL produce an executive summary documenting business risks in non-technical language
4. WHEN all testing phases complete, THE Test_Harness SHALL produce a technical report containing all Findings with severity scoring, reproduction steps, and suggested fixes
5. WHEN all testing phases complete, THE Test_Harness SHALL produce an Attack_Surface_Map showing all discovered endpoints and their security posture
6. WHEN all testing phases complete, THE Test_Harness SHALL produce a risk heatmap organized by feature area (Auth, RBAC, Billing, AI, API, Data, Infra)

### Requirement 12: Go/No-Go Acceptance Criteria

**User Story:** As a Pentester, I want clear pass/fail criteria for the system's security posture, so that stakeholders can make a binary resilience decision.

#### Acceptance Criteria

1. THE Test_Harness SHALL declare the system RESILIENT only when zero Critical-severity RBAC or IDOR Findings exist
2. THE Test_Harness SHALL declare the system RESILIENT only when plan enforcement cannot be bypassed directly or via race conditions (zero Critical business logic Findings)
3. THE Test_Harness SHALL declare the system RESILIENT only when AI agents do not reveal system data, internal prompts, or cross-tenant information through prompt injection (zero Critical AI-layer Findings)
4. THE Test_Harness SHALL declare the system RESILIENT only when zero cross-tenant data leakage paths exist
5. THE Test_Harness SHALL declare the system RESILIENT only when rate limits withstand a basic abuse profile (100× sustained burst without bypass)
6. IF any one of the above RESILIENT conditions fails, THEN THE Test_Harness SHALL declare the system NOT RESILIENT and produce a remediation priority list

### Requirement 13: Scope Boundaries and Safety

**User Story:** As a Pentester, I want clearly defined scope boundaries, so that testing does not damage production systems or attack third-party services.

#### Acceptance Criteria

1. THE Pentester SHALL NOT execute infrastructure-level DoS attacks (network flooding, SYN flood, amplification attacks) outside an explicitly agreed test window
2. THE Pentester SHALL NOT direct attack traffic against third-party services (Reddit API, OpenAI API, Perplexity API, Brevo email service, DigitalOcean infrastructure APIs)
3. THE Pentester SHALL execute all destructive tests against the staging environment (staging.gorampit.com) unless explicitly authorized for production
4. IF a Critical Finding is discovered during testing that poses immediate risk to production data, THEN THE Pentester SHALL notify the system owner (Max) within 1 hour of discovery before continuing exploitation
5. THE Pentester SHALL NOT create, modify, or delete production user accounts, client records, or avatar data during testing without explicit authorization
