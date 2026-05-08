# ThreddOps Meeting Deck - Ori Baseline, Current System, Budget, and Roadmap

Meeting date: 2026-05-08
Prepared: 2026-05-07
Audience: Tzvi / business + product decision meeting
Purpose: align on what Ori had, what ThreddOps has now, what can be demonstrated, budget, and the path from AWS migration to first-client MVP and full SaaS.

## 0. Presenter Notes

Use this as a slide-by-slide meeting document. It is intentionally less code-heavy than the architecture audit and more useful for tomorrow's conversation.

Core message:

> Ori proved the operating model. ThreddOps is turning it into an auditable, scalable, safer SaaS platform. The immediate next step is to move the working backend onto the target AWS architecture, stabilize the demo/pilot workflow, and onboard the first client with human review and strict operational controls.

## 1. Executive Summary

### What Ori Had

Ori had a strong single-client operating system:

- n8n workflows
- Supabase database
- Airtable operational UI
- subreddit scraping
- AI scoring and qualification
- persona-aware comment generation
- manual review workflow
- strong prompt strategy for natural, non-sales Reddit participation

Ori's main value was product intelligence: how to identify useful Reddit opportunities and produce comments that sound like real community participation.

### What ThreddOps Has Now

ThreddOps already has the SaaS foundation:

- FastAPI backend
- PostgreSQL data model
- Celery worker pipeline
- Redis locks and rate limiting
- shared subreddit registry
- per-client thread scoring
- admin dashboard
- activity feed and audit logs
- AI cost tracking
- avatar health and Reddit status checks
- warming phases and safety checks
- emergency controls: pipeline/generation/scrape toggles and avatar freeze
- review queue with human approval
- no direct publishing automation

### What Comes Next

Next build sequence:

1. AWS production migration: EC2 + SQS + Valkey + PostgreSQL, then RDS when client count justifies it.
2. Live demo hardening: stable seeded demo, live scrape option, clean test DB, .env readiness.
3. First-client MVP: comment pipeline, review workflow, reporting, operating playbook.
4. SaaS foundation: matching layer, trust/governance, billing, RBAC, self-service, analytics.

## 2. Slide: Ori vs ThreddOps in One Table

| Area | Ori Project | ThreddOps Now | Direction |
|---|---|---|---|
| Product proof | Strong | Stronger foundation | Keep Ori lessons |
| Architecture | n8n + Supabase + Airtable | FastAPI + PostgreSQL + Celery/Redis | Move to AWS SQS/Valkey |
| Client support | Single-client | Multi-client data model emerging | Harden multi-tenant SaaS |
| Scraping | Subreddit workflows | Shared subreddit registry | Keep subreddit-first |
| AI | Very strong prompt chains | Working pipeline, simpler prompts | Adapt Ori's quality layer |
| Review | Airtable | SaaS review queue | Keep human-in-loop |
| Audit | Airtable history | AuditLog + ActivityEvent + ScrapeLog | Expand explainability |
| Safety | Mostly process/prompt rules | Safety service + phases + freeze | Add trust/matching governance |
| Demo readiness | PoC demos | Local SaaS demo ready with env | Harden for live pilot |
| SaaS readiness | Low | Medium | Needs AWS + matching + billing/RBAC |

## 3. Slide: What Was Valuable in Ori

Ori's durable advantages:

- Subreddit-first discovery model.
- Strategic filtering before generation.
- Persona selection based on thread context.
- Engagement modes: strong POV, helpful peer, reputation-building.
- Anti-sales writing rules.
- Previous-comment diversity checks.
- Manual review before publishing.

What we should not copy:

- n8n as production orchestration.
- Airtable as system of record.
- hardcoded XM Cyber-specific workflows.
- prompt-only governance.
- avatar-centric scraping loops.

## 4. Slide: Current ThreddOps System

Current working system components:

- Admin dashboard at `/admin/`.
- Client onboarding wizard.
- Shared subreddit registry and scrape queue.
- Scrape freshness tracking.
- Thread scoring by client.
- Comment draft generation and editing.
- Review queue with approve/reject/edit/posted states.
- Avatar management with active/frozen states.
- Reddit account status checks.
- Warming phase policy.
- Activity feed and audit logs.
- AI cost page.
- System health page.
- System topology dashboard panel.
- Dry-run hub is partially implemented.

Current code reality:

- The live code still uses Celery + Redis.
- The target AWS architecture is documented and accepted as SQS + Valkey.
- SQS/Valkey migration spec exists, but implementation is not complete yet.

## 5. Slide: Current Diagnostic Snapshot

Diagnostic performed on 2026-05-07:

- Reviewed `docs/`.
- Reviewed `.kiro/specs/`.
- Reviewed `.kiro/steering/`.
- Reviewed current routes, models, tasks, Docker files, and tests.
- Ran the current test suite using the local virtual environment and local PostgreSQL.

Current test result:

```text
176 passed
2 failed
5 warnings
```

The two failures are test-environment/data-isolation issues:

- `test_seed_neuroyoga`: seed skips because a NeuroYoga row already exists with incomplete subreddit assignments.
- `test_events_outside_24h_excluded`: topology aggregation test sees pre-existing events inside the 24h window.

Interpretation:

- Core product functionality is not blocked by these failures.
- Before a serious demo or CI claim, clean/reset the test DB or isolate fixtures.

## 6. Slide: What We Can Demonstrate Tomorrow

Recommended demo format: use seeded/local demo data first, then optional live Reddit/LLM flow if credentials are configured.

### Demo Flow

1. Login to admin dashboard.
2. Show top-level system view:
   - activity feed
   - pipeline controls
   - system topology panel
   - run history
3. Show client setup:
   - client profile
   - subreddits
   - keywords
   - avatars
   - onboarding wizard
4. Show subreddit-centric pipeline:
   - scrape queue
   - shared subreddit registry
   - freshness/staleness
5. Show AI pipeline:
   - scored threads
   - engage/monitor/skip logic
   - draft generation
6. Show review workflow:
   - approve
   - reject
   - edit
   - mark as manually posted
7. Show safety controls:
   - avatar freeze
   - pipeline/generation/scrape toggles
   - avatar phase
   - Reddit status
8. Show AI costs and audit logs.

### Demo Guardrails

- Do not rely on a long live Reddit scrape during the meeting.
- Keep a seeded scenario ready.
- If live credentials are available, run one small scrape and one scoring/generation flow.
- Keep publishing manual and outside the system.

## 7. Slide: Budget - Immediate Meeting/Setup Budget

From the budget sketch:

| Item | Target |
|---|---:|
| Environment/configuration budget | $50 |
| AI coding assistant budget | $100 |
| AI/LLM usage budget | $100 |
| **Immediate working budget** | **$250** |

Interpretation:

- This is enough for local/demo hardening and limited AI testing.
- It does not include meaningful human implementation time.
- It should be treated as tool/runtime budget for the next short sprint.

## 8. Slide: Budget - AWS MVP Monthly Run Rate

Target AWS MVP architecture:

```text
Route53 / DNS
  -> CloudFront + SSL
  -> EC2 Docker host
       - FastAPI app
       - workers
       - PostgreSQL initially
  -> SQS task queues
  -> ElastiCache Serverless Valkey
  -> RDS later, when client risk justifies it
```

Infrastructure budget based on current docs:

| Component | MVP Monthly Estimate |
|---|---:|
| EC2 t3.small + EBS + Elastic IP | ~$20.43 |
| SQS Standard | ~$0-$0.30 |
| Valkey Serverless | ~$6.14 |
| PostgreSQL Docker on EC2 | ~$0 |
| S3 pg_dump backup | ~$0.02 |
| Route53/CloudFront/SSL | ~$1+ depending on traffic/domain setup |
| **AWS MVP total** | **~$27-$30/month** |

Upgrade triggers:

| Trigger | Upgrade | Added Cost |
|---|---|---:|
| 5+ paying clients / data-loss risk unacceptable | RDS db.t4g.small | +~$24/mo |
| sustained EC2 CPU > 80% | t3.small -> t3.medium | +~$15/mo |
| need high availability | ALB + second EC2 | +~$35/mo |

## 9. Slide: Budget - AI / LLM Cost

AI cost is the real variable cost.

Current estimates:

| Scenario | Monthly AI Cost |
|---|---:|
| Light client | ~$21-$36 |
| Standard pilot client | ~$36-$80 |
| Heavier demo/pilot buffer | ~$100-$110 |
| 3-client early operation | ~$105/month |
| 10-client operation | ~$350/month |

Key point:

- AWS infrastructure is cheap.
- LLM usage scales with number of drafts generated.
- Human review time is a bigger margin driver than token cost.

## 10. Slide: Budget - First Client Economics

Example economics:

| Item | Monthly |
|---|---:|
| AWS shared infrastructure | ~$27-$54 |
| AI per standard client | ~$36-$80 |
| Total technical run rate for first client | ~$63-$134 |
| Possible managed-service revenue | ~$2,000/mo |
| Technical gross margin | ~93%-97% before human time |

Business note:

- The margin story is strong.
- The operational constraint is review, editing, and client management, not cloud cost.

## 11. Slide: AWS Architecture Roadmap

### Current Working Stack

```text
FastAPI + Jinja/HTMX
PostgreSQL
Celery workers
Redis broker/cache
PRAW Reddit read API
LiteLLM
Docker Compose
```

### Target Production Stack

```text
Route53 + SSL + CloudFront
EC2 Docker host
FastAPI app
SQS workers / consumer loop
SQS queues + DLQ
Valkey Serverless for locks/rate limits/results
PostgreSQL on EC2 first
RDS after first real client risk threshold
CloudWatch metrics
```

### Why This Migration Matters

- SQS gives durable task persistence.
- DLQ makes failures visible.
- Valkey removes Redis ops risk.
- CloudWatch gives queue/health metrics.
- The app can survive worker restarts without losing work.

## 12. Slide: Roadmap to First-Client MVP

### Phase 0 - Demo Stabilization

Target: 1-2 days.

- Reset/clean local test DB.
- Make sure `.env` has Reddit + LLM credentials.
- Confirm seed data is complete.
- Run migrations on a fresh DB.
- Run demo script end-to-end.
- Fix the two current test isolation failures or document them as non-demo blockers.

Exit criteria:

- Admin dashboard opens.
- Seeded client exists.
- Review queue works.
- Safety controls visible.
- At least one mocked or live pipeline run can be shown.

### Phase 1 - AWS Migration

Target: about 1-2 weeks.

- Provision EC2.
- Configure DNS/SSL.
- Deploy app Docker image.
- Move env/secrets to production-safe handling.
- Keep PostgreSQL on EC2 Docker for MVP.
- Add S3 pg_dump backup.
- Implement SQS producer/consumer.
- Add SQS queues and DLQ.
- Add Valkey connection support.
- Replace Celery Beat with scheduler/EventBridge/cron.
- Update admin health/topology to show SQS/Valkey reality.

Exit criteria:

- Existing scrape/score/generate/review workflow runs on AWS.
- Failed tasks go to DLQ.
- Logs and health checks are visible.
- Monthly AWS cost remains around $27-$30 before RDS.

### Phase 2 - First-Client MVP

Target: after AWS migration, about 1 week of hardening plus client setup.

- Onboard first client profile.
- Configure subreddits and keywords.
- Configure avatars and phases.
- Run first scrape/score/generate.
- Review and manually publish approved content.
- Track posted status and audit trail.
- Provide basic weekly report.

Exit criteria:

- First client can receive reviewed draft suggestions.
- Operator can safely approve/edit/reject.
- System has audit trail for every decision.
- No direct publishing automation is required.

## 13. Slide: Roadmap After First Client

### Phase 3 - Production-Safe Operating Layer

- Timing jitter and activity pacing.
- Subreddit rules/sensitivity intelligence.
- Stronger context assembly service.
- Comment performance tracking.
- Cascade soft delete / operational safety.
- Cleaner settings consolidation.
- Improved AI usage analytics.
- CI cleanup and regression tests for shared subreddit registry.

### Phase 4 - Matching Layer

- Separate Persona from Avatar.
- Implement persona/avatar mapping.
- Add subreddit affinity and avatar history.
- Add trust scores, sanctions, cooldowns.
- Add ranked candidate matching.
- Store rejected candidates and scoring explanations.
- Use matching before draft generation.

### Phase 5 - SaaS Platform

- RBAC and client-facing roles.
- Agency workspace model.
- Billing and plan limits.
- Customer success dashboard.
- Self-service onboarding.
- Report automation.
- RDS and horizontal worker scaling.
- Multi-client analytics.

## 14. Slide: What Is Ready vs Not Ready

### Ready for Demo

- Admin dashboard.
- Client onboarding.
- Shared subreddit registry.
- Scrape queue visibility.
- Scoring/generation/review pipeline.
- Activity feed.
- AI cost view.
- Avatar status and freeze.
- System health/topology.

### Ready for First Pilot With Hardening

- Comment pipeline.
- Human review.
- Manual publish tracking.
- Safety gates.
- Audit logs.
- Avatar phases.
- Basic reporting from existing data.

### Not Yet SaaS-Complete

- SQS/Valkey implementation.
- Billing.
- RBAC/self-service.
- Full persona/avatar matching layer.
- Trust engine.
- Comment performance tracking.
- Subreddit intelligence.
- RDS/HA production posture.
- Customer-facing reporting automation.

## 15. Slide: Spec Review Summary

`.kiro` specifications reviewed. Current implementation coverage:

| Spec Area | Status |
|---|---|
| Activity feed / transparency | Mostly implemented |
| Admin onboarding | Implemented |
| Avatar warming phases | Implemented |
| Reddit API health dashboard | Implemented |
| Shared subreddit registry | Implemented, needs more tests/cleanup |
| Scheduled scraping | Implemented, needs more tests |
| System settings UI | Mostly implemented |
| Client hub navigation | Mostly implemented, tests missing |
| Daily ops dashboard | Implemented, tasks not marked complete |
| Avatar Reddit status | Implemented, spec lacks tasks |
| System topology timeline | Mostly implemented |
| SQS/Valkey migration | Spec/ADR only, not implemented |
| Comment performance tracking | Not implemented |
| Reddit data sync | Not implemented |
| Platform readiness | Not implemented |
| OAuth per-avatar auth | Not implemented |
| Cascade delete | Not implemented |

Recommendation:

- Do not treat every `.kiro` spec as a blocking MVP requirement.
- For first client, focus only on AWS deployment, demo stability, comment pipeline, auditability, safety controls, and review workflow.

## 16. Slide: Product Strategy

Strategic positioning:

> ThreddOps is not a prompt wrapper. It is a community engagement operations platform with reputation-aware routing, human approval, audit logs, and client-specific strategy.

What becomes the moat:

- pre-warmed avatar inventory
- subreddit-native intelligence
- persona/avatar matching
- trust and health governance
- auditability
- human-in-the-loop operations
- multi-client shared ingestion

## 17. Slide: Key Risks and Mitigations

| Risk | Status | Mitigation |
|---|---|---|
| Reddit account/platform risk | Always present | human review, phases, limits, health checks |
| Weak demo due to missing credentials | Medium | use seeded demo first |
| Task failure visibility | Current gap | SQS + DLQ migration |
| Test DB contamination | Found today | reset fixtures/test DB |
| Prompt quality below Ori | Medium | port Ori strategic/naturalism layer |
| Multi-client leakage risk | Reduced, not eliminated | context assembler + tests |
| Overbuilding before first client | High | narrow MVP scope |

## 18. Slide: Decision Requests for Tomorrow

Decisions needed:

1. Approve immediate budget: $250 for environment, coding assistant, and AI test usage.
2. Approve AWS MVP architecture: EC2 + SQS + Valkey + PostgreSQL on EC2 first.
3. Decide when to add RDS: recommended after first paying client or when data loss risk becomes unacceptable.
4. Approve first-client MVP scope: comments only, no post creation required.
5. Approve no direct publishing automation for MVP.
6. Approve matching layer as post-MVP strategic system.

## 19. Slide: Recommended Next 10 Work Items

1. Clean test DB and fix the two current test failures.
2. Prepare `.env` and demo seed data.
3. Run full local demo rehearsal.
4. Provision AWS EC2 and DNS.
5. Deploy current app with Docker.
6. Add backup process for PostgreSQL.
7. Implement SQS producer/consumer and queues.
8. Move locks/rate limiter to Valkey-compatible connection.
9. Update dashboard health/topology for AWS task architecture.
10. Onboard first client and run controlled pilot workflow.

## 20. Closing Slide

Ori was the proof that the Reddit operating model can work.

ThreddOps is the path to a real business:

- backend-first
- auditable
- scalable
- safer
- multi-client
- built for human operations

The next milestone is not "full SaaS." The next milestone is a reliable first-client MVP running on AWS with a clean demo, a controlled comment pipeline, and clear operational guardrails.
