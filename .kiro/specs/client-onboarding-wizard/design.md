# Design Document

## Architecture Overview

The onboarding wizard is a **client-portal-facing** multi-step flow with server-side state persistence and AI-powered data enrichment at each step. It reuses existing Discovery, Strategy, and GEO infrastructure for the post-onboarding automation.

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLIENT ONBOARDING WIZARD                       │
│  (client_base.html, dark theme, /onboard/step/{n})              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Step 1: URL → Scraper → LLM Synthesizer → Editable Card        │
│  Step 2: Conversational Prompts → LLM Extract → Summary Card     │
│  Step 3: ICP Form (B2B/B2C toggle) → LLM Synthesize             │
│  Step 4: Upload + Guardrails → Tone Calibration Loop             │
│  Step 5: Entity Extraction → Keywords + Subreddits (AI suggest)  │
│  Step 6: Review All → Quality Gate → Activate                    │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│                   POST-ACTIVATION (automated)                     │
│                                                                   │
│  ┌──── Ops: Avatar Allocation (admin panel) ────┐               │
│  │  Assign from pool / create new               │               │
│  └──────────────────┬───────────────────────────┘               │
│                     ▼                                             │
│  ┌──── Avatar Onboarding (per avatar, auto) ────┐               │
│  │  1. Discovery Session (auto from client brief)│               │
│  │  2. Strategy Generation (+ discovery context) │               │
│  │  3. GEO Baseline (Day 1 Report)              │               │
│  │  4. First Pipeline Run                        │               │
│  │  5. Client Notification: "Avatars active"     │               │
│  └───────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

## New Services

### 1. Website Scraper Service (`app/services/onboarding/website_scraper.py`)

```python
async def scrape_company_website(url: str) -> dict:
    """Scrape company website and extract structured text.
    
    Fetches: homepage, /about, /product (if found).
    Uses: httpx + BeautifulSoup4 (no Playwright/Puppeteer).
    Timeout: 15 seconds total.
    
    Returns:
        {"pages": {"home": "...", "about": "...", "product": "..."}, 
         "title": "...", "meta_description": "...", "domain": "..."}
    """
```

### 2. Profile Synthesizer Service (`app/services/onboarding/profile_synthesizer.py`)

```python
def synthesize_company_profile(scraped_data: dict) -> dict:
    """LLM call to generate structured company profile from scraped text.
    
    Model: Gemini Flash (cheap, fast).
    
    Returns:
        {"company_name": "...", "product_description": "...", 
         "value_proposition": "...", "key_differentiators": [...],
         "industry": "...", "company_size_estimate": "..."}
    """

def extract_positioning(answers: dict) -> dict:
    """Extract pain_language, positioning_claims, competitors from Step 2 answers.
    
    Returns:
        {"company_worldview": "...", "company_problem": "...",
         "competitive_landscape": "...", "competitors": [...]}
    """

def synthesize_icp(icp_data: dict, business_type: str) -> str:
    """Convert structured ICP answers to prose icp_profiles field."""
```

### 3. Tone Calibration Service (`app/services/onboarding/tone_calibrator.py`)

```python
def generate_tone_samples(voice_context: dict) -> list[dict]:
    """Generate 5 Reddit-style sample sentences in the brand voice.
    
    voice_context includes: uploaded doc text, guardrail answers, 
    brand voice field, admired style reference.
    
    Returns: [{"id": "...", "text": "sample sentence", "subreddit_context": "r/..."}]
    """

def evaluate_calibration(ratings: dict[str, int]) -> dict:
    """Check if calibration passes (3+ ratings >= 4).
    
    Returns: {"passed": bool, "anchors": [...sentences rated 4-5],
              "loop_count": int, "needs_call": bool (if 3 loops failed)}
    """
```

### 4. Keyword & Subreddit Suggester (`app/services/onboarding/suggestion_engine.py`)

```python
def suggest_keywords(client_profile: dict, icp_data: dict) -> dict:
    """AI-powered keyword suggestion using entity extraction patterns.
    
    Reuses: discovery/entity_extractor.py patterns.
    
    Returns: {"high": [...], "medium": [...], "low": [...]}
    """

def suggest_subreddits(keywords: dict, industry: str, competitors: list) -> list[dict]:
    """Suggest ranked subreddits with rationale.
    
    Uses PRAW to verify: subscriber count, recent activity, mod strictness.
    
    Returns: [{"name": "subreddit", "rank": 1, "rationale": "...",
               "subscribers": 50000, "activity_score": "high",
               "competitor_present": true}]
    """
```

### 5. Quality Gate Service (`app/services/onboarding/quality_gate.py`)

```python
def calculate_quality_score(client: Client) -> dict:
    """Score completeness across all profile sections.
    
    Returns: {"score": 0-100, "passed": bool, "missing_fields": [...],
              "weak_fields": [...], "tone_calibrated": bool}
    """
```

### 6. Avatar Onboarding Orchestrator (`app/services/onboarding/avatar_onboarding.py`)

```python
def trigger_avatar_onboarding(db: Session, avatar_id: UUID, client_id: UUID) -> dict:
    """Orchestrate post-allocation automation for a single avatar.
    
    Sequence:
    1. Create Discovery session (auto-mode, no human confirmation)
    2. Run entity extraction + hypothesis generation + Reddit research
    3. Generate strategy (inject discovery_context)
    4. Create GeoPrompt records + trigger GEO batch
    5. Trigger first pipeline run (scrape → score → generate → EPG)
    6. Send client notification
    
    Returns: {"status": "complete/partial_failure", "steps_completed": [...]}
    """
```

## Route Structure

```
# Client-facing onboarding wizard
GET  /onboard                         → redirect to current step
GET  /onboard/step/{n}                → render step n (1-6)
POST /onboard/step/1/scrape           → trigger URL scraping (HTMX)
POST /onboard/step/1/save             → save profile data
POST /onboard/step/2/save             → save positioning data
POST /onboard/step/3/save             → save ICP data
POST /onboard/step/4/upload           → handle file upload
POST /onboard/step/4/calibrate        → generate tone samples
POST /onboard/step/4/rate             → submit ratings
POST /onboard/step/4/save             → save guardrails
POST /onboard/step/5/suggest          → trigger AI suggestions (HTMX)
POST /onboard/step/5/save             → save keywords + subreddits
POST /onboard/step/6/activate         → quality gate check + activate
GET  /onboard/complete                → confirmation page

# Free trial signup
GET  /trial                           → trial signup page
POST /trial/signup                    → create trial account + redirect to wizard
```

## Data Model Changes

### Client model additions:
```python
# New fields on Client model
onboarding_completed_at: Mapped[datetime | None]  # NULL = not completed
current_onboarding_step: Mapped[int]  # 1-6, tracks progress
onboarding_quality_score: Mapped[int | None]  # 0-100
tone_anchors: Mapped[list | None]  # JSONB, rated 4-5 sentences
uploaded_docs_text: Mapped[str | None]  # Text extracted from uploaded files
trial_expires_at: Mapped[datetime | None]  # NULL = not a trial
```

### New model: OnboardingUpload
```python
class OnboardingUpload(Base):
    """Tracks uploaded documents during onboarding."""
    id: UUID
    client_id: UUID (FK)
    filename: str
    file_type: str  # pdf, docx, txt, md
    extracted_text: Text
    uploaded_at: datetime
```

## Reuse Map

| New Component | Reuses From | How |
|---------------|------------|-----|
| Entity extraction (Step 5) | `discovery/entity_extractor.py` | Same prompt, different trigger |
| Subreddit research (Step 5) | `discovery/reddit_researcher.py` | PRAW subreddit info lookup |
| Avatar onboarding - Discovery | `discovery/session_manager.py` | Auto-created session |
| Avatar onboarding - Strategy | `services/strategy_engine.py` | `discovery_context` parameter |
| Avatar onboarding - GEO | `services/geo_query_runner.py` | `triggered_by="onboarding"` |
| Avatar onboarding - Pipeline | `tasks/ai_pipeline.py` | Existing scrape→score→generate chain |
| LLM infrastructure | `services/ai.py` | call_llm_json, call_llm, log_ai_usage |
| Keyword CRUD | `services/admin.py` | Existing keyword update logic |
| Subreddit assignment | `models/subreddit.py` | ClientSubredditAssignment |
| File text extraction | New (PyPDF2 + python-docx) | Simple text extraction |

## AI Cost Per Onboarding

| Step | Model | Calls | Est. Cost |
|------|-------|-------|-----------|
| Step 1: Profile synthesis | Gemini Flash | 1 | $0.01 |
| Step 2: Positioning extract | Gemini Flash | 1 | $0.01 |
| Step 3: ICP synthesis | Gemini Flash | 1 | $0.005 |
| Step 4: Tone calibration (per loop) | Claude Haiku | 1-3 | $0.02-0.06 |
| Step 5: Keyword suggestion | Gemini Flash | 1 | $0.01 |
| Step 5: Subreddit suggestion | Gemini Flash | 1 | $0.01 |
| **Total per onboarding** | | **6-8 calls** | **$0.05-0.10** |

Post-activation (avatar onboarding):
| Step | Model | Est. Cost |
|------|-------|-----------|
| Discovery (entity + hypothesis + research) | Gemini Flash + Haiku | $0.15 |
| Strategy generation | Claude Haiku | $0.02 |
| GEO baseline (Perplexity) | Perplexity Sonar | $0.10 |
| First pipeline (score + generate) | Flash + Sonnet | $1.20 |
| **Total per avatar** | | **~$1.50** |

## Security & Privacy

- Scraped website data: retained only as synthesized profile (raw HTML discarded after processing)
- Uploaded documents: text extracted, stored encrypted, original file NOT stored on disk
- Trial email validation: server-side domain blocklist (gmail.com, hotmail.com, yahoo.com, outlook.com, etc.)
- All onboarding data scoped to client_id — standard RBAC applies
- Tone calibration anchors: stored as JSONB, never exposed outside the generation pipeline
