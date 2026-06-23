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


async def _require_onboard_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Like get_current_user but redirects to /onboard/trial instead of /login.

    Shows a friendly message when unauthenticated users hit /onboard/step/* directly.
    """
    import uuid as _uuid
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=303, headers={"Location": "/onboard/trial?next=onboarding"})
    try:
        user_uuid = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=303, headers={"Location": "/onboard/trial?next=onboarding"})
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=303, headers={"Location": "/onboard/trial?next=onboarding"})
    return user
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
    """Load client for the current user. Redirects to trial if no client."""
    if not user.client_id:
        raise HTTPException(status_code=303, headers={"Location": "/onboard/trial?next=onboarding"})
    client = db.query(Client).filter(Client.id == user.client_id).first()
    if not client:
        raise HTTPException(status_code=303, headers={"Location": "/onboard/trial?next=onboarding"})
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
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
    url: str = Form(""),
):
    """HTMX: Scrape URL and return profile card partial. One-time only."""
    client = _get_client_for_onboarding(user, db)

    # One-time guard: if already analyzed, don't burn another LLM call
    if client.company_profile and len(client.company_profile) > 50:
        return HTMLResponse("")  # no-op, form already has data from DB

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

    # Save domain + pre-fill step 2 fields from AI analysis
    client.brand_domain = scraped.get("domain", "")
    if profile.get("customer_pain") and not client.company_worldview:
        client.company_worldview = profile["customer_pain"]
    if profile.get("unique_advantage") and not client.company_problem:
        client.company_problem = profile["unique_advantage"]
    if profile.get("competitors_inferred") and not client.competitive_landscape:
        competitors_list = profile["competitors_inferred"]
        if isinstance(competitors_list, list):
            client.competitive_landscape = ", ".join(competitors_list)
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
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
    before_product: str = Form(""),
    unique_value: str = Form(""),
    competitors: str = Form(""),
):
    """Save Step 2 — saves answers directly (AI processing already done in suggest)."""
    client = _get_client_for_onboarding(user, db)

    # Save raw answers — AI refinement already happened in "Suggest with AI" button
    if before_product.strip():
        client.company_worldview = before_product.strip()
    if unique_value.strip():
        client.company_problem = unique_value.strip()
    if competitors.strip():
        client.competitive_landscape = competitors.strip()

    if client.current_onboarding_step < 3:
        client.current_onboarding_step = 3
    db.commit()

    return RedirectResponse(url="/onboard/step/3", status_code=303)



@router.post("/step/2/suggest", response_class=HTMLResponse)
def step2_suggest(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """HTMX: AI-powered suggestions for Step 2 fields. One-time only."""
    client = _get_client_for_onboarding(user, db)

    # One-time guard
    if client.company_worldview and client.company_problem:
        return HTMLResponse("")  # no-op, form already has data from DB

    from app.services.onboarding.ai_prompts import autofill_step2
    result = autofill_step2(
        company_profile=client.company_profile or "",
        industry=client.industry or "",
        db=db,
        client_id=str(client.id),
    )

    if result.get("error"):
        return HTMLResponse(
            '<p class="text-small" style="color:var(--color-red);">AI suggestion failed. Please fill in manually.</p>'
        )

    # Save to DB immediately (one-time operation)
    if result.get("customer_pain"):
        client.company_worldview = result["customer_pain"]
    if result.get("unique_advantage"):
        client.company_problem = result["unique_advantage"]
    if result.get("competitors"):
        client.competitive_landscape = result["competitors"]
    db.commit()

    before_product = (result.get("customer_pain") or "").replace('"', '&quot;')
    unique_value = (result.get("unique_advantage") or "").replace('"', '&quot;')
    competitors = (result.get("competitors") or "").replace('"', '&quot;')

    html = f"""<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">What does your best customer say their life was like before using you?</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">Think: their frustrations, time wasted, risks they faced</p>
    <textarea name="before_product" rows="3" class="field-input" style="width:100%;" placeholder="e.g. We were drowning in vulnerability alerts with no way to know which ones actually mattered...">{before_product}</textarea>
</div>

<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">What does your product do that your top 2-3 competitors cannot?</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">Be specific. What&#39;s your unfair advantage?</p>
    <textarea name="unique_value" rows="3" class="field-input" style="width:100%;" placeholder="e.g. We simulate full attack paths across hybrid environments using a digital twin...">{unique_value}</textarea>
</div>

<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">Name your 2-3 main competitors</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">Who do prospects compare you to?</p>
    <textarea name="competitors" rows="2" class="field-input" style="width:100%;" placeholder="e.g. Tenable, Wiz, CrowdStrike Falcon Exposure">{competitors}</textarea>
</div>"""
    return HTMLResponse(html)


# --- Step 3: ICP ---


@router.get("/step/3", response_class=HTMLResponse)
def step3_get(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """Render Step 3 — ICP definition."""
    client = _get_client_for_onboarding(user, db)
    ctx = _onboarding_context(request, 3, client)

    # Parse icp_profiles back into structured fields for template
    if client.icp_profiles:
        icp = {}
        for part in client.icp_profiles.split(". "):
            if part.startswith("Titles: "):
                icp["job_titles"] = part[8:]
            elif part.startswith("Seniority: "):
                icp["seniority"] = part[11:]
            elif part.startswith("Frustration: "):
                icp["frustration"] = part[13:]
            elif part.startswith("Searches: "):
                icp["search_query"] = part[10:]
            elif part.startswith("Adjacent: "):
                icp["adjacent_icp"] = part[10:]
        if icp:
            ctx["ai_icp"] = icp
        else:
            # Fallback: unstructured text — show in frustration field as context
            ctx["ai_icp"] = {"frustration": client.icp_profiles}

    return _render_onboard("onboarding/step3.html", ctx)


@router.post("/step/3/save")
def step3_save(
    request: Request,
    user: User = Depends(_require_onboard_user),
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
    """Save Step 3 — saves ICP directly (AI processing done in suggest button)."""
    client = _get_client_for_onboarding(user, db)

    # Build ICP text from form fields (no LLM call — suggest button already did AI work)
    if business_type == "b2b":
        parts = []
        if job_titles.strip():
            parts.append(f"Titles: {job_titles.strip()}")
        if seniority.strip():
            parts.append(f"Seniority: {seniority.strip()}")
        if frustration.strip():
            parts.append(f"Frustration: {frustration.strip()}")
        if search_query.strip():
            parts.append(f"Searches: {search_query.strip()}")
        if adjacent_icp.strip():
            parts.append(f"Adjacent: {adjacent_icp.strip()}")
        client.icp_profiles = ". ".join(parts) if parts else client.icp_profiles
    else:
        parts = []
        if demographics.strip():
            parts.append(f"Demographics: {demographics.strip()}")
        if interests.strip():
            parts.append(f"Interests: {interests.strip()}")
        if frustration.strip():
            parts.append(f"Frustration: {frustration.strip()}")
        if search_query.strip():
            parts.append(f"Searches: {search_query.strip()}")
        client.icp_profiles = ". ".join(parts) if parts else client.icp_profiles

    if client.current_onboarding_step < 4:
        client.current_onboarding_step = 4
    db.commit()

    return RedirectResponse(url="/onboard/step/4", status_code=303)



@router.post("/step/3/suggest", response_class=HTMLResponse)
def step3_suggest(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """HTMX: AI-powered suggestions for Step 3 ICP fields. One-time only."""
    client = _get_client_for_onboarding(user, db)

    # One-time guard: only block if data was saved in structured format from suggest
    if client.icp_profiles and client.icp_profiles.startswith("Titles: "):
        return HTMLResponse("")  # no-op, form already has data from suggest

    from app.services.onboarding.ai_prompts import autofill_step3
    result = autofill_step3(
        company_profile=client.company_profile or "",
        company_problem=client.company_problem or "",
        competitive_landscape=client.competitive_landscape or "",
        industry=client.industry or "",
        db=db,
        client_id=str(client.id),
    )

    if result.get("error"):
        return HTMLResponse(
            '<p class="text-small" style="color:var(--color-red);">AI suggestion failed. Please fill in manually.</p>'
        )

    # Save ICP seed to DB immediately (one-time operation)
    icp_parts = []
    if result.get("job_titles"):
        icp_parts.append(f"Titles: {result['job_titles']}")
    if result.get("frustration"):
        icp_parts.append(f"Frustration: {result['frustration']}")
    if result.get("search_query"):
        icp_parts.append(f"Searches: {result['search_query']}")
    if icp_parts and not client.icp_profiles:
        client.icp_profiles = ". ".join(icp_parts)
        db.commit()

    job_titles = (result.get("job_titles") or "").replace('"', '&quot;')
    seniority = result.get("seniority") or "manager"
    frustration = (result.get("frustration") or "").replace('"', '&quot;')
    search_query = (result.get("search_query") or "").replace('"', '&quot;')
    adjacent_icp = (result.get("adjacent_icp") or "").replace('"', '&quot;')

    # Build seniority select options
    seniority_options = ""
    for val, label in [("c-level", "C-Level / VP"), ("director", "Director"), ("manager", "Manager / Lead"), ("individual", "Individual Contributor"), ("mixed", "Mixed levels")]:
        selected = "selected" if seniority in (val, "ic" if val == "individual" else val) else ""
        seniority_options += f'<option value="{val}" {selected}>{label}</option>'

    html = f"""<div>
    <label class="text-micro" style="color:var(--color-muted);">Job titles of your buyers *</label>
    <input type="text" name="job_titles" class="field-input" style="width:100%;" placeholder="e.g. CISO, VP Security, Security Architect" value="{job_titles}">
</div>
<div>
    <label class="text-micro" style="color:var(--color-muted);">Seniority level</label>
    <select name="seniority" class="field-input" style="width:100%;">
        {seniority_options}
    </select>
</div>
<div>
    <label class="text-micro" style="color:var(--color-muted);">Their day-to-day frustration *</label>
    <textarea name="frustration" rows="2" class="field-input" style="width:100%;" placeholder="e.g. Drowning in alerts, can't prioritize...">{frustration}</textarea>
</div>
<div>
    <label class="text-micro" style="color:var(--color-muted);">What do they search before finding you? *</label>
    <textarea name="search_query" rows="2" class="field-input" style="width:100%;" placeholder="e.g. 'how to prioritize vulnerabilities', 'attack path analysis tools'">{search_query}</textarea>
    <p class="text-micro" style="color:var(--color-muted);margin-top:4px;">This becomes the seed for keyword suggestions in the next step.</p>
</div>
<div>
    <label class="text-micro" style="color:var(--color-muted);">Adjacent buyer (optional)</label>
    <textarea name="adjacent_icp" rows="2" class="field-input" style="width:100%;" placeholder="e.g. Cloud Security Engineers who evaluate tools for their CISO">{adjacent_icp}</textarea>
</div>"""
    return HTMLResponse(html)


# --- Step 4: Voice & Guardrails ---


@router.get("/step/4", response_class=HTMLResponse)
def step4_get(
    request: Request,
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
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



@router.post("/step/4/suggest", response_class=HTMLResponse)
def step4_suggest(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """HTMX: AI-powered suggestions for Step 4 voice & guardrails. One-time only."""
    client = _get_client_for_onboarding(user, db)

    # One-time guard
    if client.brand_voice and len(client.brand_voice) > 30:
        return HTMLResponse("")  # no-op, form already has data from DB

    from app.services.onboarding.ai_prompts import autofill_step4
    result = autofill_step4(
        company_profile=client.company_profile or "",
        industry=client.industry or "",
        competitive_landscape=client.competitive_landscape or "",
        db=db,
        client_id=str(client.id),
    )

    if result.get("error"):
        return HTMLResponse(
            '<p class="text-small" style="color:var(--color-red);">AI suggestion failed. Please fill in manually.</p>'
        )

    # Save voice/guardrails to DB immediately (one-time operation)
    parts = []
    if result.get("brand_voice"):
        parts.append(result["brand_voice"])
    if result.get("never_associated"):
        parts.append(f"\nNEVER associated with: {result['never_associated']}")
    if result.get("legal_limits"):
        parts.append(f"\nLegal limits: {result['legal_limits']}")
    if result.get("admired_style"):
        parts.append(f"\nAdmired style: {result['admired_style']}")
    if parts and not client.brand_voice:
        client.brand_voice = "".join(parts)
        db.commit()

    never_associated = (result.get("never_associated") or "").replace('"', '&quot;')
    legal_limits = (result.get("legal_limits") or "").replace('"', '&quot;')
    admired_style = (result.get("admired_style") or "").replace('"', '&quot;')
    brand_voice = (result.get("brand_voice") or "").replace('"', '&quot;')

    html = f"""<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">What 3 things should your brand NEVER be associated with on Reddit?</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">Topics, sentiments, or associations that are off-limits</p>
    <textarea name="never_associated" rows="2" class="field-input" style="width:100%;" placeholder="e.g. Hacking tutorials, black hat activity, vendor bashing">{never_associated}</textarea>
</div>

<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">Any claims you legally cannot make?</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">Regulatory limits, unproven claims, competitor comparisons you can&#39;t back up</p>
    <textarea name="legal_limits" rows="2" class="field-input" style="width:100%;" placeholder="e.g. Cannot claim &#39;100%% breach prevention&#39;, cannot name specific customer deployments without approval">{legal_limits}</textarea>
</div>

<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">Is there a brand, person, or publication whose communication style you admire?</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">This helps calibrate the avatar&#39;s tone</p>
    <textarea name="admired_style" rows="2" class="field-input" style="width:100%;" placeholder="e.g. Krebs on Security — direct, technical, no-BS.">{admired_style}</textarea>
</div>

<div class="surface" style="padding:var(--space-3);">
    <label style="color:var(--color-white);font-weight:500;font-size:var(--text-body);display:block;margin-bottom:8px;">Describe your brand voice (optional)</label>
    <p class="text-micro" style="color:var(--color-muted);margin-bottom:8px;">How should your avatars sound? Formal/casual, technical/accessible, opinionated/neutral?</p>
    <textarea name="brand_voice" rows="3" class="field-input" style="width:100%;" placeholder="e.g. Expert, direct, slightly cynical. Anti-hype, anti-vendor-speak. Focus on what actually reduces risk.">{brand_voice}</textarea>
</div>"""
    return HTMLResponse(html)


# --- Step 5: Keywords & Subreddits ---


@router.get("/step/5", response_class=HTMLResponse)
def step5_get(
    request: Request,
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
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
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """Render Step 6 — review all + activate."""
    client = _get_client_for_onboarding(user, db)

    from app.services.onboarding.quality_gate import check_quality
    quality = check_quality(client, db=db)

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
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """Activate client — quality gate check, set active, redirect to complete."""
    client = _get_client_for_onboarding(user, db)

    from app.services.onboarding.quality_gate import check_quality
    quality = check_quality(client, db=db)

    # --- Avatar Invariant Check (BYOA requirement) ---
    from app.services.avatar_invariant import check_activation_allowed
    avatar_allowed, avatar_error = check_activation_allowed(client.id, db)
    if not avatar_allowed:
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
                error=avatar_error,
            ),
        )

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


    # Trial signal: onboarding completed (fire-and-forget)
    try:
        from app.services.trial_signal_hooks import record_trial_signal_background
        record_trial_signal_background(
            client_id=client.id,
            signal_type="onboarding_completed",
            signal_category="engagement",
            signal_value={"steps_completed": TOTAL_STEPS},
        )
    except Exception:
        pass

    return RedirectResponse(url="/onboard/complete", status_code=303)


# --- Complete ---


@router.get("/complete", response_class=HTMLResponse)
def onboard_complete(
    request: Request,
    user: User = Depends(_require_onboard_user),
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
    gotcha: str = Form(""),
):
    """Create a free trial account: User + Client (trial plan) → redirect to wizard."""
    # Honeypot: if filled, it's a bot — fake redirect
    if gotcha:
        import logging
        logging.getLogger(__name__).warning("Honeypot triggered on /trial/signup from IP %s", request.client.host)
        return RedirectResponse(url="/onboard/trial", status_code=303)
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
        max_avatars=1,
        max_comments_per_month=30,
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
    user: User = Depends(_require_onboard_user),
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


# ---------------------------------------------------------------------------
# BYOA Step 5: Avatar Provisioning (async)
# ---------------------------------------------------------------------------


@router.get("/step/5/byoa", response_class=HTMLResponse)
def step5_byoa_get(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """Render BYOA avatar step — shows username input or existing draft status."""
    client = _get_client_for_onboarding(user, db)

    from app.services.byoa_pipeline import get_active_draft_for_client
    from app.models.avatar_draft import AvatarDraft, DRAFT_STATUS_CONFIRMED, DRAFT_NON_TERMINAL_STATUSES
    from app.models.avatar import Avatar

    # Check for existing confirmed avatar
    confirmed_avatar = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client.id)), Avatar.active.is_(True))
        .first()
    )

    # Check for active (non-terminal) draft
    active_draft = get_active_draft_for_client(client.id, db)

    return _render_onboard(
        "onboarding/step5_byoa.html",
        _onboarding_context(
            request, 5, client,
            confirmed_avatar=confirmed_avatar,
            active_draft=active_draft,
        ),
    )


@router.post("/step/5/submit-username", response_class=HTMLResponse)
def step5_submit_username(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
    reddit_username: str = Form(""),
):
    """HTMX: Submit username, create AvatarDraft, return progress partial."""
    client = _get_client_for_onboarding(user, db)

    from app.services.byoa_pipeline import create_avatar_draft, BYOAError, get_active_draft_for_client, cancel_draft
    from app.models.avatar_draft import DRAFT_NON_TERMINAL_STATUSES

    # Check for existing draft — avoid re-running expensive calls
    existing = get_active_draft_for_client(client.id, db)
    if existing:
        from app.models.avatar_draft import DRAFT_STATUS_READY_FOR_REVIEW
        # If draft already has results, don't cancel — just show it
        if existing.status == DRAFT_STATUS_READY_FOR_REVIEW:
            return _render_template(
                "onboarding/partials/byoa_preview.html",
                draft=existing,
                client_id=str(client.id),
                analysis=existing.ai_analysis or {},
                profile=existing.reddit_snapshot or {},
            )
        # If same username is being re-submitted and task is running, just return progress
        if existing.is_in_progress and existing.reddit_username == reddit_username.strip().replace("u/", "").replace("/u/", "").strip():
            return _render_template(
                "onboarding/partials/byoa_progress.html",
                draft=existing,
                client_id=str(client.id),
            )
        # Different username or failed state — cancel old and proceed
        if existing.is_in_progress:
            cancel_draft(existing.id, db)

    try:
        draft = create_avatar_draft(
            reddit_username=reddit_username,
            client_id=client.id,
            user_id=user.id,
            db=db,
        )
    except BYOAError as e:
        return HTMLResponse(
            f'<div class="surface" style="padding:16px;border:1px solid var(--color-red);border-radius:8px;">'
            f'<p style="color:var(--color-red);font-size:var(--text-small);">{str(e)}</p></div>'
        )

    # Return progress polling partial
    return _render_template(
        "onboarding/partials/byoa_progress.html",
        draft=draft,
        client_id=str(client.id),
    )


@router.get("/step/5/draft-status", response_class=HTMLResponse)
def step5_draft_status(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
):
    """HTMX poll: return appropriate partial based on AvatarDraft status."""
    client = _get_client_for_onboarding(user, db)

    from app.services.byoa_pipeline import get_active_draft_for_client
    from app.models.avatar_draft import (
        DRAFT_STATUS_PENDING_FETCH, DRAFT_STATUS_ANALYZING,
        DRAFT_STATUS_READY_FOR_REVIEW, DRAFT_STATUS_FETCH_FAILED,
        DRAFT_STATUS_ANALYSIS_FAILED,
    )

    draft = get_active_draft_for_client(client.id, db)
    if not draft:
        # No draft found — show input form
        return HTMLResponse(
            '<div id="byoa-result">'
            '<p style="color:var(--color-muted);font-size:var(--text-small);">No analysis in progress.</p>'
            '</div>'
        )

    if draft.status in (DRAFT_STATUS_PENDING_FETCH, DRAFT_STATUS_ANALYZING):
        # Still processing — return polling partial
        return _render_template(
            "onboarding/partials/byoa_progress.html",
            draft=draft,
            client_id=str(client.id),
        )
    elif draft.status == DRAFT_STATUS_READY_FOR_REVIEW:
        # Ready — show preview card
        return _render_template(
            "onboarding/partials/byoa_preview.html",
            draft=draft,
            client_id=str(client.id),
            analysis=draft.ai_analysis or {},
            profile=draft.reddit_snapshot or {},
        )
    elif draft.status in (DRAFT_STATUS_FETCH_FAILED, DRAFT_STATUS_ANALYSIS_FAILED):
        # Error — show error with retry
        return _render_template(
            "onboarding/partials/byoa_error.html",
            draft=draft,
            client_id=str(client.id),
        )
    else:
        return HTMLResponse("")


@router.post("/step/5/confirm", response_class=HTMLResponse)
def step5_confirm(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
    draft_id: str = Form(""),
    display_name: str = Form(""),
    persona_bio: str = Form(""),
    tone_principles: str = Form(""),
    voice_profile_md: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
    hobby_subreddits: str = Form(""),
    business_subreddits: str = Form(""),
):
    """Confirm BYOA draft — create Avatar, advance to step 6."""
    client = _get_client_for_onboarding(user, db)

    from app.services.byoa_pipeline import confirm_avatar_draft, BYOAError
    import uuid as _uuid

    try:
        draft_uuid = _uuid.UUID(draft_id)
    except (ValueError, TypeError):
        return HTMLResponse(
            '<p style="color:var(--color-red);">Invalid draft reference</p>'
        )

    user_edits = {
        "display_name": display_name.strip(),
        "persona_bio": persona_bio.strip(),
        "tone_principles": tone_principles.strip(),
        "voice_profile_md": voice_profile_md.strip(),
        "hill_i_die_on": hill_i_die_on.strip(),
        "helpful_mode_topics": helpful_mode_topics.strip(),
        "hobby_subreddits": hobby_subreddits.strip(),
        "business_subreddits": business_subreddits.strip(),
    }

    try:
        avatar = confirm_avatar_draft(draft_uuid, user_edits, db)
    except BYOAError as e:
        return HTMLResponse(
            f'<div class="surface" style="padding:16px;border:1px solid var(--color-red);border-radius:8px;">'
            f'<p style="color:var(--color-red);">{str(e)}</p></div>'
        )

    # Advance onboarding step
    if client.current_onboarding_step < 6:
        client.current_onboarding_step = 6
    db.commit()

    # Audit
    try:
        from app.services.audit import log_action
        log_action(
            db=db,
            user_id=user.id,
            action="byoa_avatar_confirmed",
            entity_type="avatar",
            entity_id=avatar.id,
            client_id=client.id,
            details={"reddit_username": avatar.reddit_username, "display_name": avatar.display_name},
        )
    except Exception:
        pass

    # HTMX-aware redirect: form uses hx-post, so use HX-Redirect header
    return HTMLResponse(content="", headers={"HX-Redirect": "/onboard/step/6"})


@router.post("/step/5/reject", response_class=HTMLResponse)
def step5_reject(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
    draft_id: str = Form(""),
):
    """Reject draft — return to username input."""
    from app.services.byoa_pipeline import reject_avatar_draft, BYOAError
    import uuid as _uuid

    try:
        draft_uuid = _uuid.UUID(draft_id)
        reject_avatar_draft(draft_uuid, db)
    except (ValueError, TypeError, BYOAError):
        pass

    return HTMLResponse(
        '<div id="byoa-result">'
        '<p style="color:var(--color-muted);font-size:var(--text-small);margin-bottom:12px;">Draft rejected. Try a different account:</p>'
        '</div>'
    )


@router.post("/step/5/retry", response_class=HTMLResponse)
def step5_retry(
    request: Request,
    user: User = Depends(_require_onboard_user),
    db: Session = Depends(get_db),
    reddit_username: str = Form(""),
):
    """Retry — same as submit-username (cancels old, creates new)."""
    return step5_submit_username(request, user, db, reddit_username)
