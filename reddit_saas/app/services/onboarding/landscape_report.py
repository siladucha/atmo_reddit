"""Day 1 Landscape Report — auto-generated on onboarding completion.

Shows the "aha moment": threads where brand is absent, competitor mentions,
high-intent discussions, and sample AI draft previews.

Works WITHOUT avatars — uses client keywords + subreddits only.
"""

import time
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.logging_config import get_logger
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.report_generation_job import ReportGenerationJob, ReportJobEvent

logger = get_logger(__name__)


# --- Schema validation ---

_REQUIRED_REPORT_KEYS = {
    "subreddits_monitored": int,
    "threads_found": int,
    "threads_relevant": int,
    "competitor_mentions": list,
    "high_intent_threads": list,
    "brand_absent_threads": list,
    "sample_drafts": list,
    "share_of_voice": dict,
}


def _validate_report_schema(report_data: dict) -> tuple[bool, str | None]:
    """Validate report dict has all required keys with correct types. Returns (valid, error_msg)."""
    if not isinstance(report_data, dict):
        return False, "report_data is not a dict"
    for key, expected_type in _REQUIRED_REPORT_KEYS.items():
        if key not in report_data:
            return False, f"missing key: {key}"
        if not isinstance(report_data[key], expected_type):
            return False, f"key '{key}' expected {expected_type.__name__}, got {type(report_data[key]).__name__}"
    return True, None


# --- Event helpers ---

def _emit_job_event(db: Session, job_id: uuid.UUID, event_type: str, metadata: dict | None = None) -> None:
    """Append event to job audit log."""
    event = ReportJobEvent(
        job_id=job_id,
        event_type=event_type,
        event_metadata=metadata,
    )
    db.add(event)
    db.flush()


# --- Deduplication ---

def get_or_create_report_job(
    db: Session,
    client_id: uuid.UUID,
    triggered_by: str = "portal",
    onboarding_id: uuid.UUID | None = None,
) -> ReportGenerationJob:
    """Deduplication: returns existing pending/processing job or creates new one.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent races.
    If an existing active job is found, emits DEDUP_BLOCKED event and returns it.
    """
    # Check for existing active job (pending or processing)
    existing = (
        db.query(ReportGenerationJob)
        .filter(
            ReportGenerationJob.client_id == client_id,
            ReportGenerationJob.status.in_(["pending", "processing"]),
        )
        .with_for_update(skip_locked=True)
        .first()
    )

    if existing:
        _emit_job_event(db, existing.id, "DEDUP_BLOCKED", {
            "existing_job_id": str(existing.id),
            "existing_status": existing.status,
        })
        db.commit()
        return existing

    # Create new job
    job = ReportGenerationJob(
        client_id=client_id,
        onboarding_id=onboarding_id,
        status="pending",
        triggered_by=triggered_by,
    )
    db.add(job)
    db.flush()

    _emit_job_event(db, job.id, "REPORT_STARTED", {
        "triggered_by": triggered_by,
        "onboarding_id": str(onboarding_id) if onboarding_id else None,
    })
    db.commit()

    return job


# --- Query helpers ---

def get_latest_report_for_client(db: Session, client_id: uuid.UUID) -> dict | None:
    """Return most recent completed report_data, or None."""
    job = (
        db.query(ReportGenerationJob)
        .filter(
            ReportGenerationJob.client_id == client_id,
            ReportGenerationJob.status == "completed",
        )
        .order_by(ReportGenerationJob.completed_at.desc().nullslast())
        .first()
    )
    if job and job.report_data:
        return job.report_data
    return None


def get_job_status(db: Session, client_id: uuid.UUID) -> dict:
    """Return current job status for HTMX polling.

    Returns dict with: status, job_id, started_at, completed_at, error_message, error_step, report_data.
    If no job exists, returns status='none'.
    """
    job = (
        db.query(ReportGenerationJob)
        .filter(ReportGenerationJob.client_id == client_id)
        .order_by(ReportGenerationJob.created_at.desc())
        .first()
    )
    if not job:
        return {"status": "none", "job_id": None}

    result = {
        "status": job.status,
        "job_id": str(job.id),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_message": job.error_message,
        "error_step": job.error_step,
        "report_data": job.report_data if job.status == "completed" else None,
    }
    return result


# --- Tracked generation ---

def generate_landscape_report_tracked(
    db: Session,
    client_id: uuid.UUID,
    triggered_by: str = "portal",
    onboarding_id: uuid.UUID | None = None,
) -> dict:
    """Main entry point — creates job, tracks steps, validates, emits events.

    Uses case-insensitive subreddit matching (fixes casing bug).
    Returns the report dict on success, or error dict on failure.
    """
    # Step 0: Deduplication — get or create job
    job = get_or_create_report_job(db, client_id, triggered_by, onboarding_id)

    # If job was already processing (dedup), return current status
    if job.status == "processing":
        return {"status": "processing", "job_id": str(job.id)}

    # If job was already completed (shouldn't happen via dedup but guard)
    if job.status == "completed":
        return job.report_data or {"status": "completed", "job_id": str(job.id)}

    # Transition to processing
    now = datetime.now(timezone.utc)
    job.status = "processing"
    job.started_at = now
    db.commit()

    # --- Step 1: Fetch subreddits ---
    step_start = time.monotonic()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            job.status = "failed"
            job.error_step = "fetch_subreddits"
            job.error_message = "Client not found"
            db.commit()
            _emit_job_event(db, job.id, "REPORT_FAILED", {
                "error_step": "fetch_subreddits",
                "error_message": "Client not found",
            })
            db.commit()
            return {"error": "Client not found"}

        assignments = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
            .filter(
                ClientSubredditAssignment.client_id == client_id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .all()
        )
        subreddit_names = [a.subreddit.subreddit_name for a in assignments if a.subreddit]

        duration_ms = int((time.monotonic() - step_start) * 1000)
        _emit_job_event(db, job.id, "STEP_COMPLETED", {
            "step": "fetch_subreddits",
            "duration_ms": duration_ms,
            "subreddit_count": len(subreddit_names),
        })
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.error_step = "fetch_subreddits"
        job.error_message = str(e)[:500]
        db.commit()
        _emit_job_event(db, job.id, "REPORT_FAILED", {
            "error_step": "fetch_subreddits",
            "error_message": str(e)[:200],
        })
        db.commit()
        logger.exception("Landscape report failed at fetch_subreddits for client %s", client_id)
        return {"error": f"fetch_subreddits failed: {e}"}

    # --- Step 2: Fetch threads (case-insensitive matching) ---
    step_start = time.monotonic()
    try:
        week_ago = now - timedelta(days=7)
        # Build lowercase list for case-insensitive match
        subreddit_names_lower = [s.lower() for s in subreddit_names]
        threads = (
            db.query(RedditThread)
            .filter(
                func.lower(RedditThread.subreddit).in_(subreddit_names_lower),
                RedditThread.created_at >= week_ago,
            )
            .order_by(RedditThread.ups.desc().nullslast())
            .limit(100)
            .all()
        )

        duration_ms = int((time.monotonic() - step_start) * 1000)
        _emit_job_event(db, job.id, "STEP_COMPLETED", {
            "step": "fetch_threads",
            "duration_ms": duration_ms,
            "threads_found": len(threads),
        })
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.error_step = "fetch_threads"
        job.error_message = str(e)[:500]
        db.commit()
        _emit_job_event(db, job.id, "REPORT_FAILED", {
            "error_step": "fetch_threads",
            "error_message": str(e)[:200],
        })
        db.commit()
        logger.exception("Landscape report failed at fetch_threads for client %s", client_id)
        return {"error": f"fetch_threads failed: {e}"}

    # --- Step 3: Analyze threads ---
    step_start = time.monotonic()
    try:
        # Extract keywords and competitors
        keywords_data = client.keywords or {}
        all_keywords = []
        for tier in ("high", "medium", "low"):
            all_keywords.extend(keywords_data.get(tier, []))
        all_keywords_lower = [k.lower() for k in all_keywords]

        competitors = _extract_competitor_names(client.competitive_landscape)
        brand_names = [client.brand_name.lower()] if client.brand_name else []

        # Analyze threads
        competitor_mentions = []
        high_intent = []
        brand_absent = []
        relevant_count = 0

        for thread in threads:
            text = f"{thread.post_title or ''} {(thread.post_body or '')[:500]}".lower()

            # Check keyword relevance
            is_relevant = any(kw in text for kw in all_keywords_lower)
            if is_relevant:
                relevant_count += 1

            # Check competitor mentions
            for comp in competitors:
                if comp.lower() in text:
                    competitor_mentions.append({
                        "thread_title": thread.post_title or "",
                        "subreddit": thread.subreddit or "",
                        "competitor": comp,
                        "url": thread.url or "",
                        "upvotes": thread.ups or 0,
                    })
                    break

            # Check brand presence
            brand_mentioned = any(b in text for b in brand_names)

            # High-intent: relevant + high engagement + brand absent
            if is_relevant and not brand_mentioned and (thread.ups or 0) >= 5:
                high_intent.append({
                    "title": thread.post_title or "",
                    "subreddit": thread.subreddit or "",
                    "upvotes": thread.ups or 0,
                    "url": thread.url or "",
                    "why": "Relevant to your keywords, your brand not mentioned",
                })

            # Brand absent from relevant threads
            if is_relevant and not brand_mentioned:
                brand_absent.append({
                    "title": thread.post_title or "",
                    "subreddit": thread.subreddit or "",
                    "upvotes": thread.ups or 0,
                    "url": thread.url or "",
                })

        # Sort by impact
        competitor_mentions.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
        high_intent.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
        brand_absent.sort(key=lambda x: x.get("upvotes", 0), reverse=True)

        # Share of voice
        sov = {"brand": 0, "competitors": {}}
        brand_mention_count = sum(
            1 for t in threads
            if any(b in f"{t.post_title or ''} {(t.post_body or '')[:500]}".lower() for b in brand_names)
        )
        sov["brand"] = brand_mention_count
        for comp in competitors:
            count = sum(
                1 for t in threads
                if comp.lower() in f"{t.post_title or ''} {(t.post_body or '')[:500]}".lower()
            )
            if count > 0:
                sov["competitors"][comp] = count

        report = {
            "generated_at": now.isoformat(),
            "subreddits_monitored": len(subreddit_names),
            "threads_found": len(threads),
            "threads_relevant": relevant_count,
            "competitor_mentions": competitor_mentions[:10],
            "high_intent_threads": high_intent[:10],
            "brand_absent_threads": brand_absent[:15],
            "sample_drafts": [],
            "share_of_voice": sov,
        }

        duration_ms = int((time.monotonic() - step_start) * 1000)
        _emit_job_event(db, job.id, "STEP_COMPLETED", {
            "step": "analyze_threads",
            "duration_ms": duration_ms,
            "threads_relevant": relevant_count,
            "competitor_mentions_count": len(competitor_mentions),
            "high_intent_count": len(high_intent),
        })
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.error_step = "analyze_threads"
        job.error_message = str(e)[:500]
        db.commit()
        _emit_job_event(db, job.id, "REPORT_FAILED", {
            "error_step": "analyze_threads",
            "error_message": str(e)[:200],
        })
        db.commit()
        logger.exception("Landscape report failed at analyze_threads for client %s", client_id)
        return {"error": f"analyze_threads failed: {e}"}

    # --- Step 4: Validate schema ---
    valid, error_msg = _validate_report_schema(report)
    if not valid:
        job.status = "failed"
        job.error_step = "validate_schema"
        job.error_message = error_msg
        db.commit()
        _emit_job_event(db, job.id, "JSON_VALIDATION_FAILED", {
            "error_step": "validate_schema",
            "error_message": error_msg,
        })
        db.commit()
        logger.error("Landscape report schema validation failed for client %s: %s", client_id, error_msg)
        return {"error": f"schema validation failed: {error_msg}"}

    # --- Step 5: Mark completed ---
    job.status = "completed"
    job.report_data = report
    job.completed_at = datetime.now(timezone.utc)
    db.commit()

    _emit_job_event(db, job.id, "REPORT_COMPLETED", {
        "subreddits_monitored": report["subreddits_monitored"],
        "threads_found": report["threads_found"],
        "threads_relevant": report["threads_relevant"],
    })
    db.commit()

    logger.info(
        "Landscape report tracked for %s: %d threads, %d relevant, %d competitor mentions, %d high-intent",
        client.client_name, len(threads), relevant_count,
        len(competitor_mentions), len(high_intent),
    )

    return report


def generate_landscape_report(db: Session, client_id: uuid.UUID) -> dict:
    """Generate Day 1 Landscape Report for a client.

    Does NOT require avatars. Uses existing scraped threads + client keywords.
    If no threads exist yet (brand new client), triggers scraping first.

    Returns:
        {
            "generated_at": datetime,
            "subreddits_monitored": int,
            "threads_found": int,
            "threads_relevant": int,
            "competitor_mentions": [{"thread_title": ..., "subreddit": ..., "competitor": ..., "url": ...}],
            "high_intent_threads": [{"title": ..., "subreddit": ..., "upvotes": ..., "url": ..., "why": ...}],
            "brand_absent_threads": [{"title": ..., "subreddit": ..., "upvotes": ..., "url": ...}],
            "sample_drafts": [{"thread_title": ..., "subreddit": ..., "draft_text": ...}],
            "share_of_voice": {"brand": 0, "competitors": {...}},
        }
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {"error": "Client not found"}

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Get client's subreddits
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    subreddit_names = [a.subreddit.subreddit_name for a in assignments if a.subreddit]

    # Get recent threads in those subreddits
    threads = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit.in_(subreddit_names),
            RedditThread.created_at >= week_ago,
        )
        .order_by(RedditThread.ups.desc().nullslast())
        .limit(200)
        .all()
    )

    # Extract keywords and competitors
    keywords_data = client.keywords or {}
    all_keywords = []
    for tier in ("high", "medium", "low"):
        all_keywords.extend(keywords_data.get(tier, []))
    all_keywords_lower = [k.lower() for k in all_keywords]

    competitors = _extract_competitor_names(client.competitive_landscape)
    brand_names = [client.brand_name.lower()] if client.brand_name else []

    # Analyze threads
    competitor_mentions = []
    high_intent = []
    brand_absent = []
    relevant_count = 0

    for thread in threads:
        text = f"{thread.post_title or ''} {(thread.post_body or '')[:500]}".lower()

        # Check keyword relevance
        is_relevant = any(kw in text for kw in all_keywords_lower)
        if is_relevant:
            relevant_count += 1

        # Check competitor mentions
        for comp in competitors:
            if comp.lower() in text:
                competitor_mentions.append({
                    "thread_title": thread.post_title or "",
                    "subreddit": thread.subreddit or "",
                    "competitor": comp,
                    "url": thread.url or "",
                    "upvotes": thread.ups or 0,
                })
                break

        # Check brand presence
        brand_mentioned = any(b in text for b in brand_names)

        # High-intent: relevant + high engagement + brand absent
        if is_relevant and not brand_mentioned and (thread.ups or 0) >= 5:
            high_intent.append({
                "title": thread.post_title or "",
                "subreddit": thread.subreddit or "",
                "upvotes": thread.ups or 0,
                "url": thread.url or "",
                "why": "Relevant to your keywords, your brand not mentioned",
            })

        # Brand absent from relevant threads
        if is_relevant and not brand_mentioned:
            brand_absent.append({
                "title": thread.post_title or "",
                "subreddit": thread.subreddit or "",
                "upvotes": thread.ups or 0,
                "url": thread.url or "",
            })

    # Sort by impact
    competitor_mentions.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
    high_intent.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
    brand_absent.sort(key=lambda x: x.get("upvotes", 0), reverse=True)

    # Share of voice (competitor mentions vs brand mentions)
    sov = {"brand": 0, "competitors": {}}
    brand_mention_count = sum(
        1 for t in threads
        if any(b in f"{t.post_title or ''} {(t.post_body or '')[:500]}".lower() for b in brand_names)
    )
    sov["brand"] = brand_mention_count
    for comp in competitors:
        count = sum(
            1 for t in threads
            if comp.lower() in f"{t.post_title or ''} {(t.post_body or '')[:500]}".lower()
        )
        if count > 0:
            sov["competitors"][comp] = count

    report = {
        "generated_at": now.isoformat(),
        "subreddits_monitored": len(subreddit_names),
        "threads_found": len(threads),
        "threads_relevant": relevant_count,
        "competitor_mentions": competitor_mentions[:10],
        "high_intent_threads": high_intent[:10],
        "brand_absent_threads": brand_absent[:15],
        "sample_drafts": [],  # Will be populated by AI draft generation (phase 2)
        "share_of_voice": sov,
    }

    logger.info(
        "Landscape report for %s: %d threads, %d relevant, %d competitor mentions, %d high-intent",
        client.client_name, len(threads), relevant_count,
        len(competitor_mentions), len(high_intent),
    )

    return report


def _extract_competitor_names(competitive_landscape: str | None) -> list[str]:
    """Extract competitor names from text field."""
    if not competitive_landscape:
        return []
    import re
    competitors = []
    for line in competitive_landscape.split("\n"):
        line = line.strip().strip("-•*").strip()
        if not line:
            continue
        parts = re.split(r"[,;]", line)
        for part in parts:
            part = part.strip()
            if part and len(part) < 40 and len(part.split()) <= 3:
                competitors.append(part)
    return list(set(competitors))[:10]
