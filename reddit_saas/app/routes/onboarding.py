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
# Use direct Jinja2 Environment to avoid Starlette TemplateResponse cache bug
# (TypeError: unhashable type: 'dict' in jinja2/utils.py)
from jinja2 import Environment, FileSystemLoader
_jinja_env = Environment(loader=FileSystemLoader("app/templates"))

from app.version import __version__ as app_version
_jinja_env.globals["app_version"] = app_version

from app.template_filters import register_filters
register_filters(_jinja_env)


def _render_template(template_name: str, **context) -> HTMLResponse:
    """Render a Jinja2 template directly (bypasses Starlette cache bug)."""
    tmpl = _jinja_env.get_template(template_name)
    html = tmpl.render(**context)
    return HTMLResponse(content=html)

TOTAL_STEPS = 6


# --- Helpers ---



def _render_onboard(name_or_template, context=None, *, request=None, **kwargs):
    """Wrapper: renders template like TemplateResponse but using direct Jinja2."""
    if isinstance(name_or_template, str) and context is None:
        # Called as _render_onboard("template.html", {"k": "v"}, ...)
        # But with no context, just render empty
        tmpl = _jinja_env.get_template(name_or_template)
        return HTMLResponse(content=tmpl.render(**kwargs))
    
    if isinstance(context, dict):
        tmpl = _jinja_env.get_template(name_or_template)
        return HTMLResponse(content=tmpl.render(**context))
    
    # Fallback
    tmpl = _jinja_env.get_template(name_or_template)
    return HTMLResponse(content=tmpl.render())


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
    return _render_onboard(
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
    return _render_onboard(
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
    return _render_onboard(
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
    return _render_onboard(
        "onboarding/step4.html",
        _onboarding_context(request, 4, client),
    )


@router.post("/step/4/save")
async def step4_save(
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

    # Capture tone calibration anchors (sentences rated 4-5)
    form_data = await request.form()
    tone_anchors = []
    for i in range(5):
        sentence = form_data.get(f"tone_sentence_{i}", "")
        rating = form_data.get(f"tone_rating_{i}", "")
        if sentence and rating:
            try:
                r = int(rating)
                if r >= 4:
                    tone_anchors.append(sentence)
            except ValueError:
                pass
    if tone_anchors:
        # Store as part of brand_voice (few-shot anchors)
        client.brand_voice = (client.brand_voice or "") + "\n\nTone anchors (rated 4-5 by client):\n" + "\n".join(f"- {a}" for a in tone_anchors)

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
    return _render_onboard(
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

    return _render_onboard(
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
        return _render_onboard(
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

    # Trigger Day 1 scraping + landscape report (async, non-blocking)
    try:
        from app.tasks.scraping import scrape_subreddit_shared
        from app.models.subreddit import ClientSubredditAssignment, Subreddit
        subs = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .all()
        )
        for s in subs:
            scrape_subreddit_shared.delay(str(s.subreddit_id))
        logger.info("Dispatched Day 1 scraping for %d subreddits", len(subs))
    except Exception as e:
        logger.warning("Day 1 scraping dispatch failed: %s", e)

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
    return _render_onboard(
        "onboarding/complete.html",
        _onboarding_context(request, TOTAL_STEPS, client),
    )


# --- Free Trial Signup ---

# Blocked email domains (personal/free email providers)
BLOCKED_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "outlook.com",
    "yahoo.com", "yahoo.co.uk", "aol.com", "icloud.com", "me.com",
    "mac.com", "mail.com", "protonmail.com", "proton.me", "zoho.com",
    "yandex.com", "yandex.ru", "mail.ru", "live.com", "msn.com",
    "gmx.com", "gmx.net", "tutanota.com", "fastmail.com",
}


def _is_work_email(email: str) -> bool:
    """Check if email is a work email (not a personal/free provider)."""
    domain = email.lower().split("@")[-1] if "@" in email else ""
    return domain not in BLOCKED_EMAIL_DOMAINS and "." in domain


@router.get("/trial", response_class=HTMLResponse)
def trial_page(request: Request):
    """Free trial signup page — 14-day intelligence trial."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("app/templates"))
    template = env.get_template("onboarding/trial_signup.html")
    html = template.render(request=request, error=None)
    return HTMLResponse(content=html)


@router.post("/trial/signup")
def trial_signup(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    company_name: str = Form(""),
):
    """Create a free trial account: User + Client (trial plan) → redirect to wizard."""
    from app.services.auth import get_user_by_email, create_user, create_access_token
    from app.services.cookies import set_auth_cookie

    # Validate work email
    if not _is_work_email(email):
        from jinja2 import Environment, FileSystemLoader
        _env = Environment(loader=FileSystemLoader("app/templates"))
        _tmpl = _env.get_template("onboarding/trial_signup.html")
        return HTMLResponse(content=_tmpl.render(request=request, error="Please use your work email. Personal emails (Gmail, Hotmail, etc.) are not accepted."))

    # Check if email already exists
    existing = get_user_by_email(db, email)
    if existing:
        from jinja2 import Environment, FileSystemLoader
        _env = Environment(loader=FileSystemLoader("app/templates"))
        _tmpl = _env.get_template("onboarding/trial_signup.html")
        return HTMLResponse(content=_tmpl.render(request=request, error="This email is already registered. Please sign in."))

    # Create trial client
    from datetime import timedelta
    trial_client = Client(
        client_name=company_name.strip() or email.split("@")[0],
        brand_name=company_name.strip() or email.split("@")[0],
        plan_type="trial",
        max_avatars=0,
        is_active=True,
        current_onboarding_step=1,
    )
    db.add(trial_client)
    db.flush()

    # Create user linked to trial client
    user = create_user(db, email=email, password=password, full_name=full_name)
    user.role = UserRole.client_admin.value
    user.client_id = trial_client.id
    db.commit()

    # Log in immediately
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "full_name": user.full_name or "",
        "role": user.user_role.value,
        "is_superuser": False,
    })

    response = RedirectResponse(url="/onboard", status_code=303)
    set_auth_cookie(response, token)

    logger.info("Trial signup: email=%s client=%s", email, trial_client.id)

    return response


# --- Tone Calibration (Step 4 Enhancement) ---


@router.post("/step/4/calibrate", response_class=HTMLResponse)
def step4_calibrate(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate 5 sample sentences in the brand voice for calibration."""
    client = _get_client_for_onboarding(user, db)

    # Build voice context from what we have so far
    voice_context = {
        "brand_name": client.brand_name or client.client_name or "",
        "brand_voice": client.brand_voice or "",
        "company_profile": client.company_profile or "",
        "industry": client.industry or "",
        "icp_profiles": client.icp_profiles or "",
    }

    from app.services.ai import call_llm_json, log_ai_usage

    prompt = """Generate 5 sample Reddit comment sentences that match this brand's voice.
Each sentence should be something an expert with this voice might say on Reddit — helpful, opinionated, authentic.

Brand context:
- Brand: {brand_name}
- Industry: {industry}
- Voice description: {brand_voice}
- Product: {company_profile}
- ICP: {icp_profiles}

Rules:
- Each sentence is 1-2 sentences max (Reddit comment style)
- Vary the tone: one assertive, one helpful, one slightly cynical, one data-driven, one conversational
- No marketing speak, no fluff. Real Reddit expert voice.
- Each should feel like a fragment of a genuine comment

Output JSON:
{{"sentences": ["sentence 1", "sentence 2", "sentence 3", "sentence 4", "sentence 5"]}}"""

    messages = [
        {"role": "system", "content": prompt.format(**voice_context)},
        {"role": "user", "content": "Generate 5 calibration sentences."},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model="gemini/gemini-2.5-flash",
            temperature=0.8,
            max_tokens=500,
        )
        log_ai_usage(db, str(client.id), "onboarding_tone_calibration", result)
        sentences = result["data"].get("sentences", [])[:5]
    except Exception as e:
        logger.error("Tone calibration generation failed: %s", e)
        return HTMLResponse(
            '<p class="text-small" style="color:var(--color-red);">Failed to generate samples. Try again.</p>'
            '<button type="button" hx-post="/onboard/step/4/calibrate" hx-target="#calibration-area" hx-swap="innerHTML" '
            'style="padding:8px 16px;border-radius:var(--radius-input);background:var(--color-orange);color:#fff;font-weight:600;border:none;cursor:pointer;font-size:var(--text-small);margin-top:8px;">Retry</button>'
        )

    # Build rating UI
    html_parts = ['<div style="display:flex;flex-direction:column;gap:12px;">']
    html_parts.append('<p class="text-small" style="color:var(--color-green);margin-bottom:4px;">Rate each sentence: 1 = "nothing like us" → 5 = "exactly this"</p>')

    for i, sentence in enumerate(sentences):
        # Build rating buttons (avoid backslash in f-string for Python 3.11 compat)
        rating_buttons = ""
        for r in range(1, 6):
            onchange_js = "this.parentElement.parentElement.querySelectorAll(&#39;label&#39;).forEach(l=>l.style.background=&#39;transparent&#39;);this.parentElement.style.background=&#39;rgba(255,107,53,0.3)&#39;"
            rating_buttons += (
                f'<label style="cursor:pointer;padding:4px;">'
                f'<input type="radio" name="tone_rating_{i}" value="{r}" style="display:none;" '
                f'onchange="{onchange_js}">'
                f'<span style="display:inline-block;width:32px;height:32px;border-radius:50%;border:2px solid var(--color-border);line-height:32px;text-align:center;font-size:var(--text-small);font-weight:600;color:var(--color-muted);">{r}</span>'
                f'</label>'
            )
        escaped_sentence = sentence.replace('"', '&quot;')
        html_parts.append(
            f'<div style="background:var(--color-surface-alt);border-radius:8px;padding:12px 16px;">'
            f'<p style="color:var(--color-white);font-size:var(--text-body);line-height:1.5;margin-bottom:10px;font-style:italic;">&ldquo;{escaped_sentence}&rdquo;</p>'
            f'<div style="display:flex;gap:6px;">'
            f'<input type="hidden" name="tone_sentence_{i}" value="{escaped_sentence}">'
            f'{rating_buttons}'
            f'</div></div>'
        )

    html_parts.append('</div>')
    html_parts.append('<p class="text-micro" style="color:var(--color-muted);margin-top:8px;">Rate at least 3 sentences 4 or higher to proceed. Your highest-rated sentences become training anchors.</p>')
    html_parts.append('<input type="hidden" name="tone_calibration_done" value="true">')

    return HTMLResponse("\n".join(html_parts))
