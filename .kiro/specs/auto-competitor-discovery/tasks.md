# Auto Competitor Discovery — Implementation Tasks

## Task 1: Model + Migration
- [ ] Create `DiscoveredCompetitor` model (id, client_id, name, source_query, source_platform, confidence, status, confirmed_at, created_at)
- [ ] Alembic migration `acd01`
- [ ] Add relationship to Client model

## Task 2: AI Discovery Service
- [ ] Create `app/services/competitor_discovery.py`
- [ ] `discover_competitors(client)` — runs 3 Gemini Flash queries, parses, deduplicates
- [ ] Category inference from `company_profile` (simple keyword extraction)
- [ ] Dedup logic: normalize names, merge across queries, exclude own brand
- [ ] Store results as `DiscoveredCompetitor` records (status="pending")
- [ ] Pre-confirm any that match `client.competitive_landscape`

## Task 3: Celery Task
- [ ] Create `app/tasks/competitor_discovery.py`
- [ ] `auto_discover_competitors` task with DistributedLock
- [ ] Triggered from `step6_activate()` in onboarding route
- [ ] Idempotent: skip if DiscoveredCompetitor records already exist for client
- [ ] On success: send notification to client ("X competitors discovered")

## Task 4: Client Portal UI
- [ ] Create `app/templates/partials/client/competitor_review.html`
- [ ] Show pending competitors with checkboxes (confirm/reject)
- [ ] "Confirm Selected" button → POST endpoint
- [ ] "Skip for now" → use onboarding competitors only
- [ ] Show in portal home as priority card (for trial clients with pending competitors)

## Task 5: Confirmation Endpoint
- [ ] POST `/clients/{id}/competitors/confirm` — bulk confirm/reject
- [ ] On confirm → trigger Task 6 (GEO setup) + Task 7 (Discovery auto-start)
- [ ] Update DiscoveredCompetitor statuses + confirmed_at

## Task 6: Auto-GEO Setup
- [ ] `setup_geo_monitoring(client_id)` service function
- [ ] Create `GeoCompetitor` records from confirmed competitors
- [ ] Auto-generate `GeoPrompt` records from templates
- [ ] Trigger first GEO batch execution
- [ ] Log activity event: `geo_auto_configured`

## Task 7: Auto-Discovery Start
- [ ] `start_auto_discovery(client_id)` service function
- [ ] Create `DiscoverySession` with brief from onboarding data
- [ ] Run entity extraction (or skip — use onboarding entities directly)
- [ ] Trigger research phase
- [ ] Log activity event: `discovery_auto_started`

## Task 8: Timeout + Operator Fallback
- [ ] Add to daily Celery Beat: `check_pending_competitor_reviews`
- [ ] If pending > 48h → notify operator
- [ ] Admin endpoint: confirm competitors on behalf of client

## Task 9: Integration + Testing
- [ ] Wire trigger in `step6_activate()`
- [ ] Test flow: onboarding complete → discovery → review → GEO + Discovery auto-start
- [ ] Test idempotency (double trigger)
- [ ] Test skip path (client clicks "Skip")
- [ ] Test timeout path (48h, operator notified)

## Task 10: Deploy
- [ ] Run migration on staging
- [ ] Test full flow with test client
- [ ] Deploy to production
- [ ] Monitor first real trial client through the flow
