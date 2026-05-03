# Status Report — May 1, 2026 (Day 1)

## Partnership Agreement

- **Structure:** 50/50 partnership
- **Max Breger:** Tech (all development)
- **Tzvi Vaknin:** Business (clients, marketing, content review)
- **Entity:** Cyprus company (Tzvi as CEO, EU citizenship)
- **Funding:** Prepaid pilot client (~$4K setup + ~$2K/mo)

---

## Completed Today

### Analysis
- Reviewed all 25+ files from Ori's handoff package
- Analyzed all 9 n8n workflows, extracted prompts and strategy
- Researched competitor ReddGrow (pricing, features, internal architecture)
- Analyzed ReddGrow founder's LinkedIn post about their AI agent setup

### Documentation Created
- `memory.md` — Project knowledge base
- `file_index.md` — Full file inventory with explanations
- `ai_cost_benchmark.md` — AI token cost analysis per client
- `letter_to_tzvi.md` — Initial analysis and proposal (sent)
- `call_notes_tzvi.md` — Call preparation notes
- `status_report_may1_en.md` — This report

### Development Started
- Initialized `reddit_saas/` project
- Set up FastAPI skeleton, config, database layer
- Started database models (User, Client)

### Key Decisions Made
- Build SaaS from scratch (no n8n/Airtable)
- Stack: FastAPI + Jinja2/HTMX + PostgreSQL + Celery + Redis + PRAW + LiteLLM
- Take from Ori: prompts, strategy, voice profiles, keywords, DB schema concepts
- Discard from Ori: n8n workflows, Airtable, Supabase dependency

---

## AI Cost Benchmark

Based on Ori's actual prompts extracted from workflow JSONs:

| Daily operation | Count | Model | Cost/day |
|----------------|-------|-------|----------|
| Scoring posts | 200 | Gemini Flash | $0.06 |
| Persona selection | 15 | Claude Sonnet | $0.23 |
| Comment generation | 15 | Claude Sonnet | $0.54 |
| Comment editor | 15 | Claude Sonnet | $0.23 |
| Hobby comments | 15 | Gemini Flash | $0.03 |
| Post drafts | 2 | Claude Sonnet | $0.10 |
| **Total/day** | | | **$1.19** |

**Monthly AI cost per client: $36–80** (depending on volume and retries)

Note: Ori reported ~$200/mo. Difference likely due to: no prompt caching, OpenRouter markup, retries (maxTries=5 in his workflows), and development/testing overhead.

**Question for Tzvi:** Can you confirm with Ori — was $200 for one month of production, or does it include development/testing? And what was the daily volume (comments/day)?

---

## Infrastructure Budget (per client)

| Item | Monthly |
|------|---------|
| AI / LLM API | $36–80 |
| VPS (shared) | $10–20 |
| Domain + SSL | ~$1 |
| **Total** | **$50–100** |

At $2K/mo client price → **~95% gross margin on infrastructure**

---

## Waiting On

| From | What | Status |
|------|------|--------|
| Tzvi | First client brief | ⏳ |
| Tzvi | Functional requirements (UI/UX, sample screens) | ⏳ |
| Tzvi | Exact AI token costs from Ori | ⏳ |
| Tzvi | Reddit API credentials or account | ⏳ |
| Tzvi | Pricing model + pilot onboarding strategy | ⏳ |
| Tzvi | Legal disclaimer + abuse policy draft | ⏳ |
| Tzvi | Sample Reddit avatars (personas + subreddits) | ⏳ |

---

## Roadmap

### Phase 1 — MVP for First Client (~80–100 hours)

**Stage 1A: Core Pipeline (weeks 1–3)**
- Architecture + DB + Auth + Docker
- Reddit API integration (PRAW)
- AI pipeline (scoring + persona routing + comment generation)
- Review UI (Jinja2 + HTMX)

→ **Result:** Working pipeline. First client can start reviewing AI-generated comments.

**Stage 1B: Polish + Reliability (weeks 3–5)**
- Persona system + hobby karma pipeline
- Celery jobs + scheduling
- Tracking + basic analytics
- Prompt tuning on real data

→ **Result:** Production-ready MVP.

### Phase 2 — Multi-tenant + 2 More Clients (weeks 6–8)
- Client onboarding via UI
- Avatar/subreddit configuration through interface
- Subreddit auto-suggest
- Shadowban detection

### Phase 3 — SaaS Features (ongoing)
- Analytics dashboard
- Slack integration
- Content repurposing
- Semi-automated posting
- Knowledge lake
- Billing

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Reddit avatar bans | Medium | Human-in-the-loop, hobby karma, invite-only model |
| Reddit API restrictions | Low | Free script-type app sufficient for reading |
| AI hallucinations | Medium | Editor prompt + human review |
| Prompt quality below Ori's | Medium | Use Ori's prompts as baseline, tune on real data |
| Pilot client delay | Medium | Building client-independent components now |

---

## Next Steps (Max)
1. Continue building DB models and API skeleton (not blocked by client brief)
2. Build Reddit API integration (universal, works for any client)
3. Build AI pipeline wrapper (scoring + generation)
4. Wait for Tzvi's deliverables to configure first client

---

*Next report: after receiving first client brief from Tzvi.*
