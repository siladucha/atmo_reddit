"""Engineering Memory service — creates/manages bug reports in PostgreSQL."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.bug_report import BugReport

logger = get_logger(__name__)

# Screenshots saved here — accessible via /static/uploads/bugs/
UPLOAD_DIR = Path("app/static/uploads/bugs")


def _truncate_title(what_happened: str) -> str:
    """Truncate to first sentence if longer than 100 chars."""
    if len(what_happened) <= 100:
        return what_happened.strip()
    for delimiter in (".", "!", "?"):
        idx = what_happened.find(delimiter)
        if 0 < idx <= 100:
            return what_happened[: idx + 1].strip()
    return what_happened[:97].strip() + "..."


def _build_problem_text(form_data: dict) -> str:
    """Concatenate form fields into a Problem description."""
    parts = []
    for key, label in [
        ("what_happened", "What happened"),
        ("where", "Where"),
        ("expected", "Expected"),
        ("actual_result", "Actual result"),
    ]:
        val = form_data.get(key, "").strip()
        if val:
            parts.append(f"{label}: {val}")
    return "\n\n".join(parts)


def _build_reporter(form_data: dict) -> str:
    """Return reporter identification with role context."""
    email = form_data.get("email", "").strip()
    role = form_data.get("reporter_role", "").strip()
    name = form_data.get("reporter_name", "").strip()
    parts = []
    if name:
        parts.append(name)
    if email:
        parts.append(email)
    if role:
        parts.append(f"[{role}]")
    return " — ".join(parts) if parts else "Client"


def _get_next_bug_id(db: Session) -> str:
    """Get next sequential BUG-XXX ID."""
    # Find highest numeric suffix
    from sqlalchemy import text
    result = db.execute(
        text("SELECT bug_id FROM bug_reports ORDER BY id DESC LIMIT 1")
    ).scalar()
    
    if result:
        import re
        match = re.search(r"BUG-(\d+)", result)
        if match:
            next_num = int(match.group(1)) + 1
            return f"BUG-{next_num:03d}"
    return "BUG-001"


async def save_screenshot(file) -> str | None:
    """Save uploaded screenshot to disk, return public URL path."""
    if not file or not file.filename:
        return None

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        ext = ".png"
    filename = f"{uuid.uuid4().hex[:12]}{ext}"
    filepath = UPLOAD_DIR / filename

    content = await file.read()
    if not content:
        return None

    filepath.write_bytes(content)
    logger.info("Screenshot saved: %s (%d bytes)", filepath, len(content))
    return f"/static/uploads/bugs/{filename}"


def create_incident(db: Session, form_data: dict) -> BugReport:
    """Create a new bug report in PostgreSQL.

    Args:
        db: SQLAlchemy session.
        form_data: Dict with keys: what_happened, where, expected,
                   actual_result, email, reporter_role, reporter_name,
                   screenshot_url, environment.

    Returns:
        The created BugReport instance.
    """
    bug_id = _get_next_bug_id(db)
    title = _truncate_title(form_data.get("what_happened", "Untitled"))
    problem = _build_problem_text(form_data)
    reporter = _build_reporter(form_data)

    bug = BugReport(
        bug_id=bug_id,
        title=title,
        problem=problem,
        reporter=reporter,
        reporter_role=form_data.get("reporter_role", ""),
        status="Reported",
        environment=form_data.get("environment", "prod"),
        screenshot_url=form_data.get("screenshot_url"),
        source_url=form_data.get("source_url"),
    )

    db.add(bug)
    db.commit()
    db.refresh(bug)

    logger.info("Created bug report: %s — %s (reporter: %s)", bug.bug_id, bug.title[:50], reporter)
    return bug


def get_bug_reports(db: Session, status: str | None = None, category: str | None = None,
                    environment: str | None = None, limit: int = 100) -> list[BugReport]:
    """Query bug reports with optional filters."""
    q = db.query(BugReport).filter(BugReport.id > 0)
    if status:
        q = q.filter(BugReport.status == status)
    if category:
        q = q.filter(BugReport.category == category)
    if environment:
        q = q.filter(BugReport.environment == environment)
    return q.order_by(BugReport.created_at.desc()).limit(limit).all()


def update_bug_status(db: Session, bug_id: str, status: str, **kwargs) -> BugReport | None:
    """Update bug report status and optional fields."""
    bug = db.query(BugReport).filter(BugReport.bug_id == bug_id).first()
    if not bug:
        return None

    bug.status = status

    if status == "Fixed" and not bug.fixed_at:
        bug.fixed_at = datetime.now(timezone.utc)
    if status == "Verified" and not bug.verified_at:
        bug.verified_at = datetime.now(timezone.utc)

    for key in ("root_cause", "fix", "rule", "protection", "category",
                "risk_level", "verified_by", "verification_comment"):
        if key in kwargs and kwargs[key] is not None:
            setattr(bug, key, kwargs[key])

    db.commit()
    db.refresh(bug)
    return bug
