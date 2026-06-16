# Tasks — MVP Scope

## Task 1: Data Model Changes
- [ ] Add to Client model: `current_onboarding_step` (Integer, default=0), `onboarding_completed_at` (DateTime nullable)
- [ ] Create Alembic migration
- [ ] Verify existing fields cover all onboarding outputs: company_profile, company_worldview, company_problem, competitive_landscape, brand_voice, icp_profiles, keywords, brand_domain, industry

## Task 2: Website Scraper Service
- [ ] Create `app/services/onboarding/__init__.py`
- [ ] Create `app/services/onboarding/website_scraper.py`
- [ ] `scrape_company_website(url: str) -> dict` — httpx async, 15s timeout
- [ ] Fetch homepage, detect /about and /product links, fetch those too
- [ ] BeautifulSoup: strip nav/footer/script/style, extract main text content
- [ ] Return `{"pages": {...}, "title": "...", "meta_description": "...", "domain": "..."}`
- [ ] Graceful failure: return `{"error": "...", "pages": {}}` on any exception
- [ ] Add httpx + beautifulsoup4 to pyproject.toml if not present

## Task 3: AI Prompts (Profile Synthesizer + Positioning Extractor + ICP Synthesizer + Subreddit Suggester)
- [ ] Create `app/services/onboarding/ai_prompts.py`
- [ ] `synthesize_profile(scraped_data: dict) -> dict` — Gemini Flash, JSON output: company_name, product_description, value_proposition, differentiators, industry, company_size
- [ ] `extract_positioning(answers: dict) -> dict` — Gemini Flash, JSON output: company_worldview, company_problem, competitive_landscape, competitor_names
- [ ] `synthesize_icp(form_data: dict, business_type: str) -> str` — Gemini Flash, returns prose icp_profiles
- [ ] `suggest_keywords(profile: dict, icp: str, competitors: list) -> dict` — Gemini Flash, returns {"high": [...], "medium": [...], "low": [...]}
- [ ] `suggest_subreddits(keywords: dict, industry: str, competitors: list) -> list[dict]` — Gemini Flash, returns [{"name": "...", "rationale": "...", "audience_fit": "high/medium/low"}]
- [ ] All use `call_llm_json()` with Pydantic schema validation
- [ ] All log usage via `log_ai_usage(operation="onboarding_*")`

## Task 4: Onboarding Routes
- [ ] Create `app/routes/onboarding.py`
- [ ] GET `/onboard` — check user has client_id, redirect to current step
- [ ] GET `/onboard/step/1` — render Step 1 (URL input + manual fields)
- [ ] POST `/onboard/step/1/scrape` — HTMX: scrape URL, return profile card partial
- [ ] POST `/onboard/step/1/save` — save profile fields to Client, advance step
- [ ] GET `/onboard/step/2` — render Step 2 (3 conversational prompts)
- [ ] POST `/onboard/step/2/save` — AI extract, save, advance step
- [ ] GET `/onboard/step/3` — render Step 3 (B2B/B2C toggle + ICP form)
- [ ] POST `/onboard/step/3/save` — AI synthesize, save, advance step
- [ ] GET `/onboard/step/4` — render Step 4 (guardrail questions)
- [ ] POST `/onboard/step/4/save` — save brand_voice + guardrails, advance step
- [ ] GET `/onboard/step/5` — render Step 5 (keywords + subreddits)
- [ ] POST `/onboard/step/5/suggest` — HTMX: AI suggest keywords + subreddits
- [ ] POST `/onboard/step/5/save` — save confirmed keywords + subreddits, advance step
- [ ] GET `/onboard/step/6` — render Step 6 (review all)
- [ ] POST `/onboard/step/6/activate` — quality check, set is_active + onboarding_completed_at, redirect to complete
- [ ] GET `/onboard/complete` — confirmation page
- [ ] Register router in main.py
- [ ] All routes: require get_current_user, check user.client_id exists
- [ ] Resume logic: if step > current_onboarding_step, redirect back

## Task 5: Templates (6 steps + complete + progress partial)
- [ ] Create `app/templates/onboarding/` directory
- [ ] `step1.html` — URL input field, "Analyze" button (HTMX), profile card (editable fields), manual fallback, Next button
- [ ] `step2.html` — 3 textareas with conversational labels, AI summary card (HTMX partial on save), Next button
- [ ] `step3.html` — B2B/B2C toggle (JS show/hide), Primary ICP fields, Optional Adjacent ICP accordion, Next button
- [ ] `step4.html` — 3 guardrail questions (textareas), optional brand_voice textarea, Next button
- [ ] `step5.html` — Keyword chips (AI-suggested, confirm/reject + add custom), Subreddit list with rationale cards (accept/reject), plan tier limit display, Next button
- [ ] `step6.html` — Summary of all sections (read-only cards with "Edit" links back to each step), quality warnings if fields missing, "Start Building Your Presence" CTA button
- [ ] `complete.html` — Success message, "Check back in 24-48 hours", what happens next
- [ ] `partials/onboarding_progress.html` — Step indicator (6 dots/labels, current highlighted)
- [ ] All extend `client_base.html`, dark theme, mobile-friendly
- [ ] HTMX: scrape loading, suggest loading, inline edit

## Task 6: Avatar Onboarding Orchestrator
- [ ] Create `app/services/onboarding/avatar_onboarding.py`
- [ ] `trigger_avatar_onboarding(db, avatar_id, client_id) -> dict`
- [ ] Step 1: Check if Discovery session already exists for client (24h idempotency)
- [ ] Step 2: If not, create Discovery session using client profile as brief (auto mode)
- [ ] Step 3: Run entity extraction (sync call to existing entity_extractor)
- [ ] Step 4: Run hypothesis generation (existing hypothesis_engine)
- [ ] Step 5: Generate strategy (existing strategy_engine with discovery_context)
- [ ] Step 6: Trigger first pipeline (score_threads + generate_comments via Celery delay)
- [ ] Step 7: Emit activity event "avatar_onboarding_complete"
- [ ] Handle errors per step: log + continue. Return {"completed_steps": [...], "failed_steps": [...]}
- [ ] Create Celery task wrapper: `app/tasks/onboarding.py` → `run_avatar_onboarding.delay(avatar_id, client_id)`
- [ ] Register task in worker.py

## Task 7: Admin Hook — Auto-trigger on Avatar Assignment
- [ ] In admin avatar assignment route: after successful assignment, check `client.onboarding_completed_at is not None`
- [ ] If yes: dispatch `run_avatar_onboarding.delay(avatar_id, client_id)`
- [ ] Show toast in admin UI: "Avatar onboarding triggered automatically"
- [ ] If no (client not onboarded yet): skip, no auto-trigger

## Task 8: Quality Gate (Simple)
- [ ] Create `app/services/onboarding/quality_gate.py`
- [ ] `check_quality(client: Client) -> dict` — returns {"can_activate": bool, "missing": [...]}
- [ ] Required for activation: client_name, brand_name, company_profile (non-empty), company_problem (non-empty), icp_profiles (non-empty), at least 3 keywords, at least 1 subreddit
- [ ] Optional (warning but not blocking): brand_voice, competitive_landscape, brand_domain
- [ ] Used in Step 6 activate endpoint: if not can_activate, return 422 with missing fields list

## Task 9: Integration & Polish
- [ ] Test full flow: step 1 → 6 → activation
- [ ] Test resume: leave at step 3, come back, data preserved
- [ ] Test scraper fallback: invalid URL → manual form
- [ ] Test AI failure: LLM timeout → graceful degradation (show manual fields)
- [ ] Verify RBAC: client_manager can access /onboard, client_viewer cannot start new onboarding
- [ ] Verify data isolation: one client's onboarding data not visible to another
- [ ] Add /onboard link to portal sidebar (show only if onboarding_completed_at is NULL)
