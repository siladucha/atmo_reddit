"""Client Onboarding Wizard — AI-driven 6-step setup flow.

Routes:
- GET  /onboard           → redirect to current step
- GET  /onboard/step/{n}  → render step
- POST /onboard/step/1/scrape  → HTMX: scrape URL
- POST /onboard/step/{n}/save  → save step data + advance
- POST /onboard/step/5/suggest → HTMX: AI suggestions
- POST /onboard/step/6/activate → quality gate + activate
- GET  /onboard/complete  → confirmation page
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user
from app.logging_config import get_logger
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole

logger = get_logger(__name__)

router = APIRouter(prefix="/onboard", tags=["onboarding"])
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled

from app.template_filters import register_filters
register_filters(templates.env)

TOTAL_STEPS = 6


# --- Helpers ---


def _get_client_for_onboarding(user: User, db: Session) -> Client:
    """Load client for the current user. Raises 404 if no client."""
    if not user.client_id:
        raise HTTPException(status_code=404, detail="No client associated with your account")
    client = db.query(Client).filter(Client.id == user.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _onboarding_context(request: Request, step: int, client: Client, **extra) -> dict:
    """Build template context for onboarding steps."""
    return {
        "request": request,
        "step": step,
        "total_steps": TOTAL_STEPS,
        "client": client,
        "client_id": str(client.id),
        "client_name": client.client_name or "",
        **extra,
    }


# --- Main redirect ---


@router.get("", response_class=HTMLResponse)
def onboard_redirect(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Redirect to current onboarding step (resume support)."""
    client = _get_client_for_onboarding(user, db)

    # If onboarding already completed, redirect to portal
    if client.onboarding_completed_at:
        return RedirectResponse(url=f"/clients/{client.id}/home", status_code=303)

    current_step = client.current_onboarding_step or 1
    if current_step < 1:
        current_step = 1
    if current_step > TOTAL_STEPS:
        current_step = TOTAL_STEPS

    return RedirectResponse(url=f"/onboard/step/{current_step}", status_code=303)


# --- Step 1: Company Profile ---


@router.get("/step/1", response_class=HTMLResponse)
def step1_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render Step 1 — URL input + company profile."""
    client = _get_client_for_onboarding(user, db)
    return templates.TemplateResponse(
        "onboarding/step1.html",
        _onboarding_context(request, 1, client),
    )


@router.post("/step/1/scrape", response_class=HTMLResponse)
async def step1_scrape(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    url: str = Form(""),
):
    """HTMX: Scrape URL and return profile card partial."""
    client = _get_client_for_onboarding(user, db)

    if not url.strip():
        return HTMLResponse('<p class="text-red-400 text-sm">Please enter a URL</p>')

    # Scrape website
    from app.services.onboarding.website_scraper import scrape_company_website_sync
    scraped = scrape_company_website_sync(url.strip())

    if scraped.get("error") and not scraped.get("pages"):
        return HTMLResponse(
            f'<p class="text-amber-400 text-sm">Could not auto-detect your profile: {scraped["error"]}. '
            f'Please fill in the fields manually below.</p>'
        )

    # AI synthesize profile
    from app.services.onboarding.ai_prompts import synthesize_profile
    profile = synthesize_profile(scraped, db=db, client_id=str(client.id))

    if profile.get("error"):
        return HTMLResponse(
            '<p class="text-amber-400 text-sm">AI analysis failed. Please fill in the fields manually.</p>'
        )

    # Save domain
    client.brand_domain = scraped.get("domain", "")
    db.commit()

    # Return editable profile card as HTML partial
    html = f'''
    <div class="surface" style="padding:var(--space-3);border:1px solid var(--color-green);border-radius:var(--radius-card);">
        <p style="color:var(--color-green);font-size:var(--text-small);margin-bottom:12px;">Profile auto-detected from {scraped.get("domain", url)}</p>
        <input type="hidden" name="ai_detected" value="true">
        <div style="display:grid;gap:12px;">
            <div>
                <label class="text-micro" style="color:var(--color-muted);">Company Name</label>
                <input type="text" name="client_name" value="{profile.get('company_name', client.client_name or '')}"
                       class="field-input" style="width:100%;">
            </div>
            <div>
                <label class="text-micro" style="color:var(--color-muted);">Product Description</label>
                <textarea name="company_profile" rows="3" class="field-input" style="width:100%;">{profile.get('product_description', '')}</textarea>
            </div>
            <div>
                <label class="text-micro" style="color:var(--color-muted);">Value Proposition</label>
                <textarea name="value_proposition" rows="2" class="field-input" style="width:100%;">{profile.get('value_proposition', '')}</textarea>
            </div>
            <div>
                <label class="text-micro" style="color:var(--color-muted);">Industry</label>
                <input type="text" name="industry" value="{profile.get('industry', '')}"
                       class="field-input" style="width:100%;">
            </div>
        </div>
    </div>'''
    return HTMLResponse(html)


@router.post("/step/1/save")
def step1_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_name: str = Form(""),
    brand_name: str = Form(""),
    company_profile: str = Form(""),
    value_proposition: str = Form(""),
    industry: str = Form(""),
    brand_domain: str = Form(""),
):
    """Save Step 1 data and advance to Step 2."""
    client = _get_client_for_onboarding(user, db)

    if client_name.strip():
        client.client_name = client_name.strip()
    if brand_name.strip():
        client.brand_name = brand_name.strip()
    if company_profile.strip():
        # Combine product description + value proposition
        full_profile = company_profile.strip()
        if value_proposition.strip():
            full_profile += f"\n\nValue proposition: {value_proposition.strip()}"
        client.company_profile = full_profile
    if industry.strip():
        client.industry = industry.strip()
    if brand_domain.strip():
        client.brand_domain = brand_domain.strip()

    # Advance step
    if client.current_onboarding_step < 2:
        client.current_onboarding_step = 2
    db.commit()

    return RedirectResponse(url="/onboard/step/2", status_code=303)


# --- Step 2: Problem & Competitors ---


@router.get("/step/2", response_class=HTMLResponse)
def step2_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render Step 2 — conversational prompts."""
    client = _get_client_for_onboarding(user, db)
    return templates.TemplateResponse(
        "onboarding/step2.html",
        _onboarding_context(request, 2, client),
    )


@router.post("/step/2/save")
def step2_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    before_product: str = Form(""),
    unique_value: str = Form(""),
    competitors: str = Form(""),
):
    """Save Step 2 — AI extracts positioning, saves to client."""
    client = _get_client_for_onboarding(user, db)

    # AI extraction
    from app.services.onboarding.ai_prompts import extract_positioning
    answers = {
        "before_product": before_product,
        "unique_value": unique_value,
        "competitors": competitors,
    }
    result = extract_positioning(answers, db=db, client_id=str(client.id))

    if not result.get("error"):
        if result.get("company_worldview"):
            client.company_worldview = result["company_worldview"]
        if result.get("company_problem"):
            client.company_problem = result["company_problem"]
        if result.get("competitive_landscape"):
            client.competitive_landscape = result["competitive_landscape"]
    else:
        # Fallback: save raw answers
        client.company_worldview = before_product.strip() or client.company_worldview
        client.company_problem = unique_value.strip() or client.company_problem
        client.competitive_landscape = competitors.strip() or client.competitive_landscape

    if client.current_onboarding_step < 3:
        client.current_onboarding_step = 3
    db.commit()

    return RedirectResponse(url="/onboard/step/3", status_code=303)


# --- Step 3: ICP ---


@router.get("/step/3", response_class=HTMLResponse)
def step3_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render Step 3 — ICP definition."""
    client = _get_client_for_onboarding(user, db)
    return templates.TemplateResponse(
        "onboarding/step3.html",
        _onboarding_context(request, 3, client),
    )


@router.post("/step/3/save")
def step3_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    business_type: str = Form("b2b"),
    job_titles: str = Form(""),
    seniority: str = Form(""),
    frustration: str = Form(""),
    search_query: str = Form(""),
    adjacent_icp: str = Form(""),
    demographics: str = Form(""),
    interests: str = Form(""),
):
    """Save Step 3 — AI synthesizes ICP."""
    client = _get_client_for_onboarding(user, db)

    from app.services.onboarding.ai_prompts import synthesize_icp
    form_data = {
        "job_titles": job_titles,
        "seniority": seniority,
        "frustration": frustration,
        "search_query": search_query,
        "adjacent_icp": adjacent_icp,
        "demographics": demographics,
        "interests": interests,
    }
    icp_text = synthesize_icp(form_data, business_type, db=db, client_id=str(client.id))
    client.icp_profiles = icp_text

    if client.current_onboarding_step < 4:
        client.current_onboarding_step = 4
    db.commit()

    return RedirectResponse(url="/onboard/step/4", status_code=303)


# --- Step 4: Voice & Guardrails ---


@router.get("/step/4", response_class=HTMLResponse)
def step4_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render Step 4 — guardrail questions."""
    client = _get_client_for_onboarding(user, db)
    return templates.TemplateResponse(
        "onboarding/step4.html",
        _onboarding_context(request, 4, client),
    )


@router.post("/step/4/save")
def step4_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    never_associated: str = Form(""),
    legal_limits: str = Form(""),
    admired_style: str = Form(""),
    brand_voice: str = Form(""),
):
    """Save Step 4 — guardrails and brand voice."""
    client = _get_client_for_onboarding(user, db)

    # Combine guardrails into brand_voice field
    parts = []
    if brand_voice.strip():
        parts.append(brand_voice.strip())
    if never_associated.strip():
        parts.append(f"\nNEVER associated with: {never_associated.strip()}")
    if legal_limits.strip():
        parts.append(f"\nLegal limits: {legal_limits.strip()}")
    if admired_style.strip():
        parts.append(f"\nAdmired style: {admired_style.strip()}")

    client.brand_voice = "\n".join(parts) if parts else client.brand_voice

    if client.current_onboarding_step < 5:
        client.current_onboarding_step = 5
    db.commit()

    return RedirectResponse(url="/onboard/step/5", status_code=303)


# --- Step 5: Keywords & Subreddits ---


@router.get("/step/5", response_class=HTMLResponse)
def step5_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render Step 5 — keywords and subreddits."""
    client = _get_client_for_onboarding(user, db)
    return templates.TemplateResponse(
        "onboarding/step5.html",
        _onboarding_context(request, 5, client, keywords=client.keywords or {}),
    )


@router.post("/step/5/suggest", response_class=HTMLResponse)
def step5_suggest(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HTMX: AI-powered keyword + subreddit suggestions."""
    client = _get_client_for_onboarding(user, db)

    from app.services.onboarding.ai_prompts import suggest_keywords, suggest_subreddits

    # Extract competitor names from competitive_landscape
    competitors = []
    if client.competitive_landscape:
        # Simple extraction: look for capitalized multi-word names
        import re
        competitors = re.findall(r'\b[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*\b', client.competitive_landscape)
        competitors = list(set(competitors))[:5]

    # Suggest keywords
    keywords = suggest_keywords(
        company_profile=client.company_profile or "",
        icp_profiles=client.icp_profiles or "",
        competitors=competitors,
        industry=client.industry or "",
        db=db,
        client_id=str(client.id),
    )

    # Suggest subreddits
    subreddits = suggest_subreddits(
        keywords=keywords,
        industry=client.industry or "",
        competitors=competitors,
        company_profile=client.company_profile or "",
        db=db,
        client_id=str(client.id),
    )

    # Build HTML partial with suggestions
    html_parts = ['<div id="suggestions-result">']

    # Keywords section
    html_parts.append('<h3 class="text-h3" style="margin-bottom:12px;">Suggested Keywords</h3>')
    html_parts.append('<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;">')
    for tier, kws in keywords.items():
        if tier == "error":
            continue
        for kw in (kws or []):
            color = {"high": "var(--color-green)", "medium": "var(--color-orange)", "low": "var(--color-muted)"}.get(tier, "var(--color-muted)")
            html_parts.append(
                f'<label style="display:inline-flex;align-items:center;gap:6px;padding:4px 12px;'
                f'border-radius:var(--radius-pill);border:1px solid {color};cursor:pointer;">'
                f'<input type="checkbox" name="keywords" value="{kw}|{tier}" checked '
                f'style="accent-color:{color};">'
                f'<span style="color:{color};font-size:var(--text-small);">{kw}</span>'
                f'<span style="color:var(--color-muted);font-size:var(--text-micro);">{tier}</span>'
                f'</label>'
            )
    html_parts.append('</div>')

    # Subreddits section
    html_parts.append('<h3 class="text-h3" style="margin-bottom:12px;">Suggested Subreddits</h3>')
    html_parts.append('<div style="display:flex;flex-direction:column;gap:8px;">')
    for sub in subreddits:
        fit_color = {"high": "var(--color-green)", "medium": "var(--color-orange)", "low": "var(--color-muted)"}.get(sub.get("audience_fit", ""), "var(--color-muted)")
        html_parts.append(
            f'<label style="display:flex;align-items:flex-start;gap:12px;padding:12px;'
            f'background:var(--color-surface-alt);border-radius:var(--radius-card);cursor:pointer;">'
            f'<input type="checkbox" name="subreddits" value="{sub.get("name", "")}" checked '
            f'style="margin-top:4px;accent-color:var(--color-orange);">'
            f'<div style="flex:1;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="color:var(--color-white);font-weight:600;">r/{sub.get("name", "")}</span>'
            f'<span style="font-size:var(--text-micro);color:{fit_color};">{sub.get("audience_fit", "")} fit</span>'
            f'<span style="font-size:var(--text-micro);color:var(--color-muted);">{sub.get("type", "")}</span>'
            f'</div>'
            f'<p style="font-size:var(--text-small);color:var(--color-muted);margin-top:4px;">{sub.get("rationale", "")}</p>'
            f'</div></label>'
        )
    html_parts.append('</div>')
    html_parts.append('</div>')

    return HTMLResponse("\n".join(html_parts))


@router.post("/step/5/save")
async def step5_save(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save Step 5 — confirmed keywords + subreddits."""
    client = _get_client_for_onboarding(user, db)

    form = await request.form()
    raw_keywords = form.getlist("keywords")
    raw_subreddits = form.getlist("subreddits")

    # Parse keywords: "phrase|tier" format
    keywords_dict = {"high": [], "medium": [], "low": []}
    for kw_raw in raw_keywords:
        if "|" in kw_raw:
            phrase, tier = kw_raw.rsplit("|", 1)
            if tier in keywords_dict:
                keywords_dict[tier].append(phrase)
            else:
                keywords_dict["medium"].append(phrase)
        else:
            keywords_dict["medium"].append(kw_raw)

    client.keywords = keywords_dict

    # Create subreddit assignments
    from app.models.subreddit import Subreddit, ClientSubredditAssignment
    from sqlalchemy import func

    for sub_name in raw_subreddits:
        sub_name = sub_name.strip().lower()
        if not sub_name:
            continue

        # Get or create Subreddit record
        subreddit = (
            db.query(Subreddit)
            .filter(func.lower(Subreddit.subreddit_name) == sub_name)
            .first()
        )
        if not subreddit:
            subreddit = Subreddit(subreddit_name=sub_name, is_active=True)
            db.add(subreddit)
            db.flush()

        # Check if assignment already exists
        existing = (
            db.query(ClientSubredditAssignment)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.subreddit_id == subreddit.id,
            )
            .first()
        )
        if not existing:
            assignment = ClientSubredditAssignment(
                client_id=client.id,
                subreddit_id=subreddit.id,
                is_active=True,
                type="professional",
            )
            db.add(assignment)

    if client.current_onboarding_step < 6:
        client.current_onboarding_step = 6
    db.commit()

    return RedirectResponse(url="/onboard/step/6", status_code=303)


# --- Step 6: Review & Activate ---


@router.get("/step/6", response_class=HTMLResponse)
def step6_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render Step 6 — review all + activate."""
    client = _get_client_for_onboarding(user, db)

    from app.services.onboarding.quality_gate import check_quality
    quality = check_quality(client)

    # Get subreddit count
    from app.models.subreddit import ClientSubredditAssignment
    sub_count = (
        db.query(ClientSubredditAssignment)
        .filter(ClientSubredditAssignment.client_id == client.id, ClientSubredditAssignment.is_active.is_(True))
        .count()
    )

    return templates.TemplateResponse(
        "onboarding/step6.html",
        _onboarding_context(
            request, 6, client,
            quality=quality,
            subreddit_count=sub_count,
        ),
    )


@router.post("/step/6/activate")
def step6_activate(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate client — quality gate check, set active, redirect to complete."""
    client = _get_client_for_onboarding(user, db)

    from app.services.onboarding.quality_gate import check_quality
    quality = check_quality(client)

    if not quality["can_activate"]:
        # Return to step 6 with error
        from app.models.subreddit import ClientSubredditAssignment
        sub_count = (
            db.query(ClientSubredditAssignment)
            .filter(ClientSubredditAssignment.client_id == client.id, ClientSubredditAssignment.is_active.is_(True))
            .count()
        )
        return templates.TemplateResponse(
            "onboarding/step6.html",
            _onboarding_context(
                request, 6, client,
                quality=quality,
                subreddit_count=sub_count,
                error="Please complete the required fields before activating.",
            ),
        )

    # Activate
    client.is_active = True
    client.onboarding_completed_at = datetime.now(timezone.utc)
    db.commit()

    # Emit activity event
    try:
        from app.services.transparency import record_activity_event
        record_activity_event(
            db=db,
            client_id=str(client.id),
            event_type="client_onboarded",
            description=f"Client {client.client_name} completed onboarding",
            details={"triggered_by": user.email},
        )
        db.commit()
    except Exception:
        pass

    logger.info("Client onboarded: %s (id=%s) by user %s", client.client_name, client.id, user.email)

    return RedirectResponse(url="/onboard/complete", status_code=303)


# --- Complete ---


@router.get("/complete", response_class=HTMLResponse)
def onboard_complete(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirmation page after successful onboarding."""
    client = _get_client_for_onboarding(user, db)
    return templates.TemplateResponse(
        "onboarding/complete.html",
        _onboarding_context(request, TOTAL_STEPS, client),
    )
