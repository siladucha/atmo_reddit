"""GEO/AEO Prompt Monitoring admin routes.

Provides UI for managing prompts, competitors, viewing execution history,
and triggering manual runs. All routes require superuser access.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from app.templating import Jinja2Templates
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.client import Client
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_execution import GeoExecutionBatch, GeoFrequencyMetric, GeoQueryResult
from app.models.geo_prompt import GeoPrompt
from app.models.user import User
from app.services import audit as audit_service
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/clients", tags=["admin-geo"])
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Main GEO page
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo", response_class=HTMLResponse)
def geo_main_page(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Main GEO monitoring page for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )

    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )

    batches = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.client_id == client_id)
        .order_by(desc(GeoExecutionBatch.started_at))
        .limit(20)
        .all()
    )

    # Compute visibility report for the analytics dashboard section
    from app.services.visibility_report import compute_visibility_report
    report = compute_visibility_report(db, client_id, include_excerpts=True)

    return templates.TemplateResponse(
        request,
        "admin_geo.html",
        {
            "user": current_user,
            "client": client,
            "client_id": str(client_id),
            "prompts": prompts,
            "competitors": competitors,
            "batches": batches,
            "report": report,
        },
    )


# ---------------------------------------------------------------------------
# Prompt CRUD (HTMX partials)
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo/prompts", response_class=HTMLResponse)
def get_prompts_partial(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: prompt list."""
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_prompts.html",
        {
            "prompts": prompts,
            "client_id": str(client_id),
        },
    )


@router.post("/{client_id}/geo/prompts", response_class=HTMLResponse)
def create_prompt(
    request: Request,
    client_id: uuid.UUID,
    prompt_text: str = Form(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Create a new GEO prompt."""
    # Validate length
    prompt_text = prompt_text.strip()
    if len(prompt_text) < 10 or len(prompt_text) > 1000:
        raise HTTPException(status_code=400, detail="Prompt must be 10-1000 characters")

    # Plan limit check — GEO prompts
    from app.services.plan_limits import check_geo_prompt_limit
    allowed, limit_msg, _current, _limit = check_geo_prompt_limit(db, client_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=limit_msg)

    # Check duplicate
    existing = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.prompt_text == prompt_text)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate prompt text")

    prompt = GeoPrompt(
        client_id=client_id,
        prompt_text=prompt_text,
        category=category.strip() or None,
        created_by=current_user.id,
    )
    db.add(prompt)
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        entity_type="geo_prompt",
        entity_id=prompt.id,
        client_id=client_id,
        details={"prompt_text": prompt_text[:100]},
    )

    # Return updated prompt list
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_prompts.html",
        {
            "prompts": prompts,
            "client_id": str(client_id),
        },
    )


@router.post("/{client_id}/geo/prompts/{prompt_id}/toggle", response_class=HTMLResponse)
def toggle_prompt(
    request: Request,
    client_id: uuid.UUID,
    prompt_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Toggle a prompt active/inactive."""
    prompt = db.query(GeoPrompt).filter(GeoPrompt.id == prompt_id, GeoPrompt.client_id == client_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt.is_active = not prompt.is_active
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle",
        entity_type="geo_prompt",
        entity_id=prompt.id,
        client_id=client_id,
        details={"is_active": prompt.is_active},
    )

    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_prompts.html",
        {
            "prompts": prompts,
            "client_id": str(client_id),
        },
    )


@router.delete("/{client_id}/geo/prompts/{prompt_id}", response_class=HTMLResponse)
def delete_prompt(
    request: Request,
    client_id: uuid.UUID,
    prompt_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Soft-delete a prompt (deactivate)."""
    prompt = db.query(GeoPrompt).filter(GeoPrompt.id == prompt_id, GeoPrompt.client_id == client_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt.is_active = False
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="deactivate",
        entity_type="geo_prompt",
        entity_id=prompt.id,
        client_id=client_id,
    )

    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_prompts.html",
        {
            "prompts": prompts,
            "client_id": str(client_id),
        },
    )


# ---------------------------------------------------------------------------
# Competitor CRUD (HTMX partials)
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo/competitors", response_class=HTMLResponse)
def get_competitors_partial(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: competitor list."""
    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_competitors.html",
        {
            "competitors": competitors,
            "client_id": str(client_id),
        },
    )


@router.post("/{client_id}/geo/competitors", response_class=HTMLResponse)
def create_competitor(
    request: Request,
    client_id: uuid.UUID,
    competitor_name: str = Form(...),
    competitor_domain: str = Form(""),
    aliases: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Create a new competitor entity."""
    competitor_name = competitor_name.strip()
    if not competitor_name:
        raise HTTPException(status_code=400, detail="Competitor name is required")

    # Plan limit check — GEO competitors
    from app.services.plan_limits import check_geo_competitor_limit
    allowed, limit_msg, _current, _limit = check_geo_competitor_limit(db, client_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=limit_msg)

    # Check duplicate name
    existing = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.competitor_name == competitor_name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate competitor name")

    # Parse aliases (comma-separated)
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []

    comp = GeoCompetitor(
        client_id=client_id,
        competitor_name=competitor_name,
        competitor_domain=competitor_domain.strip() or None,
        aliases=alias_list,
    )
    db.add(comp)
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="create",
        entity_type="geo_competitor",
        entity_id=comp.id,
        client_id=client_id,
        details={"name": competitor_name},
    )

    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_competitors.html",
        {
            "competitors": competitors,
            "client_id": str(client_id),
        },
    )


@router.post("/{client_id}/geo/competitors/{comp_id}/toggle", response_class=HTMLResponse)
def toggle_competitor(
    request: Request,
    client_id: uuid.UUID,
    comp_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Toggle a competitor active/inactive."""
    comp = db.query(GeoCompetitor).filter(GeoCompetitor.id == comp_id, GeoCompetitor.client_id == client_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail="Competitor not found")

    comp.is_active = not comp.is_active
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle",
        entity_type="geo_competitor",
        entity_id=comp.id,
        client_id=client_id,
        details={"is_active": comp.is_active},
    )

    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_competitors.html",
        {
            "competitors": competitors,
            "client_id": str(client_id),
        },
    )


# ---------------------------------------------------------------------------
# Execution history + Run Now
# ---------------------------------------------------------------------------


@router.get("/{client_id}/geo/history", response_class=HTMLResponse)
def get_history_partial(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: execution history."""
    batches = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.client_id == client_id)
        .order_by(desc(GeoExecutionBatch.started_at))
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_history.html",
        {
            "batches": batches,
            "client_id": str(client_id),
        },
    )


@router.get("/{client_id}/geo/batch/{batch_id}", response_class=HTMLResponse)
def get_batch_detail(
    request: Request,
    client_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """HTMX partial: batch detail view with per-prompt results."""
    batch = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.id == batch_id, GeoExecutionBatch.client_id == client_id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get frequency metrics for this batch
    metrics = (
        db.query(GeoFrequencyMetric)
        .filter(GeoFrequencyMetric.execution_batch_id == batch_id)
        .all()
    )

    # Get prompts for display
    prompt_ids = list(set(m.prompt_id for m in metrics))
    prompts_map = {}
    if prompt_ids:
        prompts_list = db.query(GeoPrompt).filter(GeoPrompt.id.in_(prompt_ids)).all()
        prompts_map = {p.id: p for p in prompts_list}

    return templates.TemplateResponse(
        request,
        "partials/geo_batch_detail.html",
        {
            "batch": batch,
            "metrics": metrics,
            "prompts_map": prompts_map,
            "client_id": str(client_id),
        },
    )


@router.post("/{client_id}/geo/run-now", response_class=HTMLResponse)
def run_now(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Trigger an immediate GEO execution batch for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    from app.services.geo_query_runner import run_geo_batch_for_client

    batch = run_geo_batch_for_client(
        db=db,
        client=client,
        triggered_by="manual",
        user_id=current_user.id,
    )

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="trigger",
        entity_type="geo_batch",
        entity_id=batch.id if batch else None,
        client_id=client_id,
        details={"triggered_by": "manual", "status": batch.status if batch else "no_prompts"},
    )

    # Return updated history
    batches = (
        db.query(GeoExecutionBatch)
        .filter(GeoExecutionBatch.client_id == client_id)
        .order_by(desc(GeoExecutionBatch.started_at))
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_history.html",
        {
            "batches": batches,
            "client_id": str(client_id),
        },
    )


# ---------------------------------------------------------------------------
# GEO monitoring toggle
# ---------------------------------------------------------------------------


@router.post("/{client_id}/geo/toggle", response_class=HTMLResponse)
def toggle_geo_monitoring(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Toggle GEO monitoring on/off for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.geo_monitoring_enabled = not client.geo_monitoring_enabled
    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="toggle",
        entity_type="geo_monitoring",
        client_id=client_id,
        details={"geo_monitoring_enabled": client.geo_monitoring_enabled},
    )

    # Re-render the full page via redirect header for HTMX
    return HTMLResponse(
        content="",
        headers={"HX-Redirect": f"/admin/clients/{client_id}/geo"},
    )


# ---------------------------------------------------------------------------
# AI-powered prompt generation
# ---------------------------------------------------------------------------

_GENERATE_PROMPTS_SYSTEM = """You are an expert in AI search optimization (AEO/GEO).
Your task: generate buyer-intent prompts that a potential customer would type into
AI assistants (ChatGPT, Perplexity, Google Gemini) when researching solutions in the
client's industry.

These prompts will be used to monitor whether the client's brand appears in AI-generated answers.

RULES:
- Generate exactly {count} prompts
- Each prompt should be a natural question a buyer would ask an AI assistant
- Cover different intent stages: awareness, consideration, comparison, decision
- Include problem-focused queries ("How to solve X?"), category queries ("Best tools for Y"),
  comparison queries ("X vs Y"), and use-case queries ("How to achieve Z?")
- Do NOT mention the client's brand in the prompts — these are discovery queries
- Keep prompts between 20 and 120 characters
- Use the client's industry, keywords, and competitor names for context
- Assign a category to each prompt: "problem", "comparison", "category", "use_case", or "opinion"
- Return valid JSON

OUTPUT FORMAT:
{{"prompts": [{{"text": "...", "category": "..."}}]}}
"""


@router.post("/{client_id}/geo/generate-prompts", response_class=HTMLResponse)
def generate_prompts_ai(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Generate buyer-intent prompts using AI based on client profile."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Plan-based limit check for GEO prompts
    from app.services.plan_limits import check_geo_prompt_limit, get_plan_limit
    allowed, limit_msg, active_count, plan_limit = check_geo_prompt_limit(db, client_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=limit_msg)

    remaining_slots = plan_limit - active_count

    # Generate up to 10 prompts (or remaining slots, whichever is smaller)
    count = min(10, remaining_slots)

    # Build context from client data
    keywords_str = ""
    if client.keywords:
        all_kw = []
        for priority, kw_list in client.keywords.items():
            if isinstance(kw_list, list):
                all_kw.extend(kw_list)
        keywords_str = ", ".join(all_kw[:30])

    # Get existing competitor names for context
    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active.is_(True))
        .all()
    )
    competitor_names = [c.competitor_name for c in competitors]

    # Get existing prompts to avoid duplicates
    existing_prompts = (
        db.query(GeoPrompt.prompt_text)
        .filter(GeoPrompt.client_id == client_id)
        .all()
    )
    existing_texts = {p.prompt_text.lower().strip() for p in existing_prompts}

    user_content = f"""Client: {client.brand_name}
Industry: {client.industry or 'not specified'}
Keywords: {keywords_str or 'not specified'}
Company profile: {(client.company_profile or '')[:500]}
Competitors: {', '.join(competitor_names) if competitor_names else 'not specified'}

Generate {count} buyer-intent prompts for GEO/AEO monitoring."""

    from app.config import get_config
    from app.services.ai import call_llm_json

    try:
        result = call_llm_json(
            messages=[
                {"role": "system", "content": _GENERATE_PROMPTS_SYSTEM.format(count=count)},
                {"role": "user", "content": user_content},
            ],
            model=get_config("llm_scoring_model"),
            temperature=0.7,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error(f"Failed to generate GEO prompts for client {client_id}: {e}")
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)[:200]}")

    # Log AI cost
    from app.services.ai import log_ai_usage
    log_ai_usage(
        db=db,
        client_id=str(client_id),
        operation="geo_generate_prompts",
        result=result,
        triggered_by="manual",
    )

    data = result.get("data", {})
    generated = data.get("prompts", [])

    if not generated:
        raise HTTPException(status_code=500, detail="AI returned no prompts")

    # Insert generated prompts (skip duplicates)
    created_count = 0
    for item in generated:
        text = item.get("text", "").strip()
        category = item.get("category", "").strip() or None

        if not text or len(text) < 10 or len(text) > 1000:
            continue
        if text.lower().strip() in existing_texts:
            continue

        prompt = GeoPrompt(
            client_id=client_id,
            prompt_text=text,
            category=category,
            created_by=current_user.id,
        )
        db.add(prompt)
        existing_texts.add(text.lower().strip())
        created_count += 1

    db.commit()

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="generate",
        entity_type="geo_prompts",
        client_id=client_id,
        details={
            "generated": created_count,
            "model": result.get("model", "unknown"),
            "cost_usd": result.get("cost_usd"),
        },
    )

    logger.info(f"Generated {created_count} GEO prompts for client {client.brand_name}")

    # Return updated prompt list
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id)
        .order_by(desc(GeoPrompt.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_prompts.html",
        {
            "prompts": prompts,
            "client_id": str(client_id),
        },
    )


# ---------------------------------------------------------------------------
# AI-powered competitor suggestion
# ---------------------------------------------------------------------------

_SUGGEST_COMPETITORS_SYSTEM = """You are an expert competitive intelligence analyst.
Your task: identify the top competitors for a given brand in its industry.

For each competitor, provide:
- Company/product name (the commonly known brand name)
- Domain (their primary website, without https://)
- Aliases (alternative names, abbreviations, or product names they are known by)

RULES:
- Suggest exactly {count} competitors
- Focus on DIRECT competitors (same market category, similar target audience)
- Include a mix of: established leaders, growing challengers, and niche alternatives
- Do NOT include the client's own brand
- Do NOT include generic/broad companies unless they directly compete in this niche
- Prioritize competitors that are likely to appear in AI search results for the same buyer queries
- Use real company/product names — no made-up entities
- Domain should be the primary marketing domain (e.g., "crowdstrike.com", not "crowdstrike.io")
- Aliases should include abbreviations, product sub-brands, or informal names (e.g., ["CS", "CrowdStrike Falcon"])

OUTPUT FORMAT (valid JSON — MUST be a JSON object with a "competitors" array):
{{"competitors": [{{"name": "...", "domain": "...", "aliases": ["...", "..."]}}]}}

IMPORTANT: Always return ALL competitors inside the "competitors" array, even if suggesting only one.
"""


@router.post("/{client_id}/geo/suggest-competitors", response_class=HTMLResponse)
def suggest_competitors_ai(
    request: Request,
    client_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Suggest competitors using AI based on client profile and industry."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Plan-based limit check for GEO competitors
    from app.services.plan_limits import check_geo_competitor_limit, get_plan_limit
    allowed, limit_msg, active_count, plan_limit = check_geo_competitor_limit(db, client_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=limit_msg)

    remaining_slots = plan_limit - active_count

    # Suggest up to 10 competitors (or remaining slots, whichever is smaller)
    count = min(10, remaining_slots)

    # Build context from client data
    keywords_str = ""
    if client.keywords:
        all_kw = []
        for priority, kw_list in client.keywords.items():
            if isinstance(kw_list, list):
                all_kw.extend(kw_list)
        keywords_str = ", ".join(all_kw[:30])

    # Get existing competitors to avoid duplicates
    existing_competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .all()
    )
    existing_names = {c.competitor_name.lower().strip() for c in existing_competitors}

    # Get existing prompts for additional context
    existing_prompts = (
        db.query(GeoPrompt.prompt_text)
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active.is_(True))
        .limit(10)
        .all()
    )
    sample_prompts = [p.prompt_text for p in existing_prompts]

    user_content = f"""Client brand: {client.brand_name}
Industry: {client.industry or 'not specified'}
Keywords: {keywords_str or 'not specified'}
Company profile: {(client.company_profile or '')[:500]}
Already tracked competitors: {', '.join(existing_names) if existing_names else 'none'}
Sample buyer-intent prompts: {'; '.join(sample_prompts[:5]) if sample_prompts else 'none'}

Suggest {count} direct competitors that are NOT already tracked."""

    from app.config import get_config
    from app.services.ai import call_llm_json, log_ai_usage

    system_prompt = _SUGGEST_COMPETITORS_SYSTEM.format(count=count)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # Try primary model (Gemini Flash), fallback to Claude Haiku if <3 results
    result = None
    suggested = []

    for model_name in ["anthropic/claude-haiku-4-5", get_config("llm_scoring_model")]:
        try:
            result = call_llm_json(
                messages=messages,
                model=model_name,
                temperature=0.7,
                max_tokens=2048,
            )
        except Exception as e:
            logger.warning(f"GEO suggest competitors failed with {model_name}: {e}")
            continue

        # Log AI cost for every attempt
        log_ai_usage(
            db=db,
            client_id=str(client_id),
            operation="geo_suggest_competitors",
            result=result,
            triggered_by="manual",
        )

        # Parse response (handle malformed formats)
        data = result.get("data", {})
        suggested = data.get("competitors", [])

        if not suggested:
            if isinstance(data, dict) and "name" in data:
                suggested = [data]
            elif isinstance(data, list):
                suggested = data

        # If got enough results, stop
        if len(suggested) >= 3:
            break
        else:
            logger.warning(
                "GEO_SUGGEST_INSUFFICIENT | model=%s | got=%d | expected=%d | retrying",
                model_name, len(suggested), count,
            )

    if not suggested:
        raise HTTPException(status_code=500, detail="AI returned no competitor suggestions")

    # Insert suggested competitors (skip duplicates)
    created_count = 0
    for item in suggested:
        name = item.get("name", "").strip()
        domain = item.get("domain", "").strip() or None
        aliases = item.get("aliases", [])

        if not name:
            continue
        if name.lower().strip() in existing_names:
            continue
        # Skip if same as client brand
        if client.brand_name and name.lower().strip() == client.brand_name.lower().strip():
            continue

        # Normalize aliases
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]
        elif isinstance(aliases, list):
            aliases = [str(a).strip() for a in aliases if str(a).strip()]
        else:
            aliases = []

        comp = GeoCompetitor(
            client_id=client_id,
            competitor_name=name,
            competitor_domain=domain,
            aliases=aliases,
        )
        db.add(comp)
        existing_names.add(name.lower().strip())
        created_count += 1

    db.commit()

    # Audit log
    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="ai_suggest",
        entity_type="geo_competitors",
        client_id=client_id,
        details={
            "suggested": created_count,
            "model": result.get("model", "unknown"),
            "cost_usd": float(result.get("cost_usd", 0)),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
        },
    )

    logger.info(
        "GEO_SUGGEST_COMPETITORS | client=%s | created=%d | model=%s | cost=$%.4f",
        client.brand_name, created_count, result.get("model", "?"), result.get("cost_usd", 0),
    )

    # Return updated competitor list
    competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id)
        .order_by(desc(GeoCompetitor.created_at))
        .all()
    )
    return templates.TemplateResponse(
        request,
        "partials/geo_competitors.html",
        {
            "competitors": competitors,
            "client_id": str(client_id),
        },
    )
