"""Client & internal email notifications — lifecycle and ops emails.

Five types:
1. Weekly Visibility Digest — sent Mon after intelligence report generation (to client)
2. Avatar Phase Milestone — sent on promotion/demotion events (to client)
3. Avatar Health Alert — sent on shadowban/freeze detection (to client)
4. Weekly System Health Report — sent Sun evening to owner/admins
5. Weekly Business Summary — sent Sun evening to partners

All emails are fire-and-forget. Failure never blocks pipeline operations.
Delivery: Brevo HTTP API (via send_task_email).

Usage from Celery tasks:
    from app.services.client_emails import send_weekly_visibility_digest
    send_weekly_visibility_digest(client_id)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _get_client_admin_emails(client_id: uuid.UUID) -> list[str]:
    """Get emails of client_admin and client_manager users for a client.

    Looks up via both User.client_id (legacy) and UserClientAssignment.
    Returns deduplicated list of active, verified emails.
    """
    from app.database import SessionLocal
    from app.models.user import User
    from app.models.user_client_assignment import UserClientAssignment

    db = SessionLocal()
    try:
        emails = set()

        # Direct client_id on User (legacy path)
        direct_users = (
            db.query(User.email)
            .filter(
                User.client_id == client_id,
                User.is_active == True,
                User.email_verified == True,
                User.role.in_(["client_admin", "client_manager", "owner", "partner"]),
            )
            .all()
        )
        for (email,) in direct_users:
            emails.add(email)

        # UserClientAssignment path
        assigned_users = (
            db.query(User.email)
            .join(
                UserClientAssignment,
                UserClientAssignment.user_id == User.id,
            )
            .filter(
                UserClientAssignment.client_id == client_id,
                UserClientAssignment.is_active == True,
                UserClientAssignment.role.in_(["client_admin", "client_manager"]),
                User.is_active == True,
                User.email_verified == True,
            )
            .all()
        )
        for (email,) in assigned_users:
            emails.add(email)

        return list(emails)
    except Exception as e:
        logger.warning("Failed to get client admin emails for %s: %s", client_id, e)
        return []
    finally:
        db.close()


def _send_client_email(
    client_id: uuid.UUID,
    subject: str,
    body_text: str,
    body_html: str,
) -> int:
    """Send email to all client admins. Returns count of successful sends."""
    from app.services.email_sender import send_task_email

    recipients = _get_client_admin_emails(client_id)
    if not recipients:
        logger.debug("No recipients for client email: client_id=%s", client_id)
        return 0

    sent = 0
    for email in recipients:
        try:
            success, _ = send_task_email(
                to=email,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                headers={"X-RAMP-Email-Type": "client_notification"},
            )
            if success:
                sent += 1
        except Exception as e:
            logger.debug("Failed to send client email to %s: %s", email, e)

    return sent


def _portal_url(client_id: uuid.UUID, path: str = "") -> str:
    """Build portal URL for client."""
    from app.config import get_config
    base = get_config("app_base_url") or "https://gorampit.com"
    return f"{base}/clients/{client_id}{path}"


# ─── 1. Weekly Visibility Digest ──────────────────────────────────────────────


def send_weekly_visibility_digest(client_id) -> bool:
    """Send weekly AI visibility summary email to client.

    Called from generate_weekly_reports_all_clients after report is published.
    Pulls latest visibility data and formats a concise digest.

    Returns True if at least one email sent successfully.
    """
    from app.database import SessionLocal
    from app.models.client import Client
    from app.services.visibility_report import compute_visibility_report

    client_uuid = uuid.UUID(str(client_id))
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_uuid).first()
        if not client or not client.is_active:
            return False

        # Get visibility data
        report_data = compute_visibility_report(db, client_uuid, include_excerpts=True)
        if not report_data.get("has_data"):
            logger.debug("No visibility data for client %s — skipping digest", client_id)
            return False

        summary = report_data["summary"]
        engines = report_data.get("engines", {})
        competitors = report_data.get("competitors", [])
        excerpts = report_data.get("excerpts", [])
        projected = report_data.get("projected", {})

        # Format
        brand_rate = summary.get("latest_brand_rate", 0)
        delta = summary.get("brand_rate_delta", 0)
        delta_str = f"+{delta}" if delta > 0 else str(delta)

        # Build engine lines
        engine_lines = []
        for eng_name, eng_data in engines.items():
            rate = eng_data.get("rate", 0)
            proj = projected.get(eng_name, 0)
            display_name = eng_name.capitalize()
            engine_lines.append(f"  • {display_name}: {rate}% (→ ~{proj}% in 6 mo)")

        # Top competitors
        competitor_lines = []
        for comp in competitors[:3]:
            name = comp.get("name", "Unknown")
            rate = comp.get("appearance_rate", 0)
            competitor_lines.append(f"  • {name}: {rate}%")

        # Excerpts
        excerpt_lines = []
        for ex in excerpts[:2]:
            text = ex.get("text", "")[:150]
            engine = ex.get("provider", "AI")
            excerpt_lines.append(f'  "{text}..." — {engine}')

        portal_link = _portal_url(client_uuid, "/visibility")

        # Plain text
        body_text = f"""Weekly AI Visibility Report — {client.brand_name}

Your brand mention rate: {brand_rate}% ({delta_str}pp vs baseline)

Per engine:
{chr(10).join(engine_lines)}

Top competitors:
{chr(10).join(competitor_lines) if competitor_lines else "  No competitor data yet"}

{f'AI mentions this week:{chr(10)}{chr(10).join(excerpt_lines)}' if excerpt_lines else ''}

View full report: {portal_link}

—
RAMP Visibility Intelligence
"""

        # HTML
        engine_html = "".join(
            f'<li><strong>{eng.capitalize()}</strong>: {engines[eng].get("rate", 0)}% '
            f'<span style="color:#22c55e">→ ~{projected.get(eng, 0)}% in 6 mo</span></li>'
            for eng in engines
        )

        competitor_html = "".join(
            f'<li>{c.get("name", "")}: {c.get("appearance_rate", 0)}%</li>'
            for c in competitors[:3]
        )

        excerpt_html = ""
        if excerpts:
            excerpt_items = "".join(
                f'<li style="font-style:italic;color:#555">"{ex.get("text", "")[:150]}..." '
                f'<span style="color:#888">— {ex.get("provider", "AI")}</span></li>'
                for ex in excerpts[:2]
            )
            excerpt_html = f'<h3 style="margin-top:20px">AI Mentions</h3><ul>{excerpt_items}</ul>'

        body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<h2 style="margin-bottom:5px">AI Visibility Report</h2>
<p style="color:#666;margin-top:0">{client.brand_name} — Weekly Digest</p>

<div style="background:#f8fafc;border-radius:8px;padding:16px;margin:16px 0">
  <div style="font-size:28px;font-weight:bold">{brand_rate}%</div>
  <div style="color:{'#22c55e' if delta >= 0 else '#ef4444'};font-size:14px">{delta_str}pp vs baseline</div>
</div>

<h3>Per Engine</h3>
<ul>{engine_html}</ul>

<h3>Top Competitors</h3>
<ul>{competitor_html if competitor_html else '<li style="color:#888">No competitor data yet</li>'}</ul>

{excerpt_html}

<div style="margin-top:24px">
  <a href="{portal_link}" style="background:#2563eb;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">View Full Report</a>
</div>

<p style="color:#888;font-size:12px;margin-top:24px">
  Projections marked with ~ are forecasts, not guarantees.<br>
  RAMP Visibility Intelligence — gorampit.com
</p>
</div>"""

        subject = f"📊 AI Visibility: {brand_rate}% ({delta_str}pp) — {client.brand_name}"

        sent = _send_client_email(client_uuid, subject, body_text, body_html)
        if sent:
            logger.info("Weekly visibility digest sent for client %s to %d recipients", client_id, sent)
        return sent > 0

    except Exception as e:
        logger.warning("Failed to send weekly visibility digest for %s: %s", client_id, e)
        return False
    finally:
        db.close()


# ─── 2. Avatar Phase Milestone ────────────────────────────────────────────────


def send_phase_milestone_email(
    client_id,
    avatar_username: str,
    event_type: str,
    previous_phase: int,
    new_phase: int,
    trigger_reason: str = "",
) -> bool:
    """Send email on avatar phase promotion or demotion.

    event_type: "phase_promotion" or "auto_downgrade"
    """
    client_uuid = uuid.UUID(str(client_id))

    if event_type == "phase_promotion":
        return _send_promotion_email(client_uuid, avatar_username, previous_phase, new_phase)
    else:
        return _send_demotion_email(client_uuid, avatar_username, previous_phase, new_phase, trigger_reason)


def _phase_description(phase: int) -> str:
    """Human-readable phase description."""
    descriptions = {
        0: "Incubation (safe communities, 1/day)",
        1: "Credibility Building (hobby communities, no brand)",
        2: "Professional Engagement (target communities, brand-eligible)",
        3: "Brand Authority (full brand integration)",
    }
    return descriptions.get(phase, f"Phase {phase}")


def _send_promotion_email(
    client_id: uuid.UUID,
    avatar_username: str,
    previous_phase: int,
    new_phase: int,
) -> bool:
    """Send celebration email on avatar promotion."""
    portal_link = _portal_url(client_id, "/avatars")

    phase_desc = _phase_description(new_phase)

    # What this means for the client
    if new_phase == 2:
        what_it_means = (
            "Your voice now engages in professional subreddits relevant to your business. "
            "Content quality and relevance will increase. Brand mentions become eligible in the next phase."
        )
    elif new_phase == 3:
        what_it_means = (
            "Your voice has earned enough community trust for brand integration. "
            "It can now naturally reference your brand when contextually relevant."
        )
    elif new_phase == 1:
        what_it_means = (
            "Your voice has cleared incubation and is building credibility in hobby communities. "
            "This foundation ensures long-term account health."
        )
    else:
        what_it_means = "Your voice is progressing through its warming phases."

    subject = f"🎉 {avatar_username} promoted to Phase {new_phase}"

    body_text = f"""Good news — Voice Promoted!

{avatar_username} has been promoted from Phase {previous_phase} to Phase {new_phase}.

New phase: {phase_desc}

What this means:
{what_it_means}

View avatar details: {portal_link}

—
RAMP Avatar Intelligence
"""

    body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<div style="background:#dcfce7;border-radius:8px;padding:16px;margin-bottom:16px">
  <h2 style="margin:0;color:#166534">🎉 Avatar Promoted!</h2>
</div>

<p><strong>{avatar_username}</strong> has graduated to the next phase:</p>

<div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:12px 16px;margin:16px 0">
  <div style="font-size:12px;color:#888">Phase {previous_phase} → Phase {new_phase}</div>
  <div style="font-size:16px;font-weight:600;margin-top:4px">{phase_desc}</div>
</div>

<p style="color:#555">{what_it_means}</p>

<div style="margin-top:24px">
  <a href="{portal_link}" style="background:#22c55e;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">View Avatar</a>
</div>

<p style="color:#888;font-size:12px;margin-top:24px">RAMP Avatar Intelligence — gorampit.com</p>
</div>"""

    sent = _send_client_email(client_id, subject, body_text, body_html)
    if sent:
        logger.info("Phase promotion email sent: %s Phase %d→%d", avatar_username, previous_phase, new_phase)
    return sent > 0


def _send_demotion_email(
    client_id: uuid.UUID,
    avatar_username: str,
    previous_phase: int,
    new_phase: int,
    trigger_reason: str,
) -> bool:
    """Send informative email on avatar demotion (not alarming, shows plan)."""
    portal_link = _portal_url(client_id, "/avatars")

    # Translate trigger reason to client language
    reason_map = {
        "low_survival_rate": "Content removal rate was above normal in target communities",
        "shadowban_detected": "Platform health issue detected (usually temporary, 3-7 days)",
        "cqs_drop": "Account quality score dropped (automatically recovers with activity)",
        "karma_drop": "Engagement quality decreased in recent activity",
    }
    client_reason = reason_map.get(trigger_reason, trigger_reason or "Automated safety adjustment")

    subject = f"ℹ️ {avatar_username} — temporary phase adjustment"

    body_text = f"""Voice Phase Adjustment

{avatar_username} has been moved from Phase {previous_phase} to Phase {new_phase}.

Reason: {client_reason}

What's happening:
• The voice continues to operate at a reduced pace
• Our system monitors recovery signals automatically
• Phase promotion will happen again once conditions are met
• No action needed from you

This is a normal part of the warming process — it protects your voice's long-term health.

View details: {portal_link}

—
RAMP Voice Intelligence
"""

    body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<div style="background:#fef3c7;border-radius:8px;padding:16px;margin-bottom:16px">
  <h2 style="margin:0;color:#92400e">ℹ️ Phase Adjustment</h2>
</div>

<p><strong>{avatar_username}</strong> has been temporarily moved to a lower phase for safety:</p>

<div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:12px 16px;margin:16px 0">
  <div style="font-size:12px;color:#888">Phase {previous_phase} → Phase {new_phase}</div>
  <div style="font-size:14px;margin-top:4px"><strong>Reason:</strong> {client_reason}</div>
</div>

<h3 style="font-size:14px;margin-bottom:8px">What's happening:</h3>
<ul style="color:#555;padding-left:20px">
  <li>Voice continues at reduced pace</li>
  <li>Recovery is monitored automatically</li>
  <li>Phase promotion resumes when conditions are met</li>
  <li><strong>No action needed from you</strong></li>
</ul>

<p style="color:#666;font-size:13px">This is a normal part of the process — it protects long-term account health and reputation.</p>

<div style="margin-top:24px">
  <a href="{portal_link}" style="background:#f59e0b;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">View Details</a>
</div>

<p style="color:#888;font-size:12px;margin-top:24px">RAMP Voice Intelligence — gorampit.com</p>
</div>"""

    sent = _send_client_email(client_id, subject, body_text, body_html)
    if sent:
        logger.info("Phase demotion email sent: %s Phase %d→%d reason=%s", avatar_username, previous_phase, new_phase, trigger_reason)
    return sent > 0


# ─── 3. Avatar Health Alert ───────────────────────────────────────────────────


def send_health_alert_email(
    client_id,
    avatar_username: str,
    health_status: str,
    detection_method: str = "",
) -> bool:
    """Send email when avatar health issue detected (shadowban, suspended, frozen).

    Tone: informative, not alarming. Shows that system is handling it.
    """
    client_uuid = uuid.UUID(str(client_id))
    portal_link = _portal_url(client_uuid, "/avatars")

    if health_status == "shadowbanned":
        emoji = "⚠️"
        title = "Health Issue Detected"
        status_text = "Visibility restriction detected"
        explanation = (
            "The platform has temporarily restricted this voice's visibility. "
            "This is usually resolved within 3-7 days. The voice has been moved to "
            "a recovery phase and our system monitors it automatically."
        )
        action = "No action needed — recovery is automatic."
    elif health_status == "suspended":
        emoji = "🔴"
        title = "Account Issue"
        status_text = "Account access restricted by platform"
        explanation = (
            "The platform has restricted access to this account. "
            "This may require manual intervention. We're investigating."
        )
        action = "Our team is looking into this. We'll update you with next steps."
    else:
        emoji = "⚠️"
        title = "Voice Paused"
        status_text = f"Status: {health_status}"
        explanation = (
            "This voice has been temporarily paused for safety. "
            "Our monitoring system will resume operations when conditions are met."
        )
        action = "No action needed — system handles recovery."

    subject = f"{emoji} {avatar_username} — {title.lower()}"

    body_text = f"""{title} — {avatar_username}

Status: {status_text}

{explanation}

{action}

Your other voices continue operating normally.

View details: {portal_link}

—
RAMP Voice Intelligence
"""

    body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<div style="background:#fef2f2;border-radius:8px;padding:16px;margin-bottom:16px">
  <h2 style="margin:0;color:#991b1b">{emoji} {title}</h2>
</div>

<p><strong>{avatar_username}</strong></p>

<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;margin:16px 0">
  <div style="font-size:14px">{status_text}</div>
</div>

<p style="color:#555">{explanation}</p>

<div style="background:#f0fdf4;border-radius:6px;padding:12px 16px;margin:16px 0">
  <strong style="color:#166534">✓ {action}</strong>
</div>

<p style="color:#666;font-size:13px">Your other voices continue operating normally.</p>

<div style="margin-top:24px">
  <a href="{portal_link}" style="background:#6b7280;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">View Voices</a>
</div>

<p style="color:#888;font-size:12px;margin-top:24px">RAMP Voice Intelligence — gorampit.com</p>
</div>"""

    sent = _send_client_email(client_uuid, subject, body_text, body_html)
    if sent:
        logger.info("Health alert email sent: %s status=%s", avatar_username, health_status)
    return sent > 0


# ─── 4. Weekly System Health Report (Admin/Owner) ─────────────────────────────


def _get_admin_emails() -> list[str]:
    """Get emails of owner and partner users."""
    from app.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        users = (
            db.query(User.email)
            .filter(
                User.is_active == True,
                User.email_verified == True,
                User.role.in_(["owner", "partner"]),
            )
            .all()
        )
        return [email for (email,) in users]
    except Exception as e:
        logger.warning("Failed to get admin emails: %s", e)
        return []
    finally:
        db.close()


def _get_owner_emails() -> list[str]:
    """Get emails of owner-role users only."""
    from app.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        users = (
            db.query(User.email)
            .filter(
                User.is_active == True,
                User.email_verified == True,
                User.role == "owner",
            )
            .all()
        )
        return [email for (email,) in users]
    except Exception as e:
        logger.warning("Failed to get owner emails: %s", e)
        return []
    finally:
        db.close()


def _get_partner_emails() -> list[str]:
    """Get emails of partner-role users only."""
    from app.database import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        users = (
            db.query(User.email)
            .filter(
                User.is_active == True,
                User.email_verified == True,
                User.role == "partner",
            )
            .all()
        )
        return [email for (email,) in users]
    except Exception as e:
        logger.warning("Failed to get partner emails: %s", e)
        return []
    finally:
        db.close()


def _collect_capacity_metrics(db) -> dict:
    """Collect server capacity metrics from /proc, disk, PostgreSQL, Redis, LLM latency.

    Works from inside Docker container (reads host kernel via /proc).
    """
    import shutil
    from sqlalchemy import text

    cap = {}

    # ─── Memory (host) ─────────────────────────────────────────────
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
        mem_total_mb = meminfo.get("MemTotal", 0) / 1024
        mem_available_mb = meminfo.get("MemAvailable", 0) / 1024
        mem_used_mb = mem_total_mb - mem_available_mb
        cap["mem_total_mb"] = round(mem_total_mb)
        cap["mem_used_mb"] = round(mem_used_mb)
        cap["mem_available_mb"] = round(mem_available_mb)
        cap["mem_pct"] = round(mem_used_mb / mem_total_mb * 100, 1) if mem_total_mb > 0 else 0
    except Exception:
        cap["mem_pct"] = 0

    # ─── CPU Load (host) ───────────────────────────────────────────
    try:
        import os
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        cap["cpu_load_1"] = float(parts[0])
        cap["cpu_load_5"] = float(parts[1])
        cap["cpu_load_15"] = float(parts[2])
        cap["cpu_cores"] = os.cpu_count() or 2
        cap["cpu_pct"] = min(round(cap["cpu_load_5"] / cap["cpu_cores"] * 100, 1), 100.0)
    except Exception:
        cap["cpu_pct"] = 0
        cap["cpu_cores"] = 2

    # ─── Disk ──────────────────────────────────────────────────────
    try:
        total, used, free = shutil.disk_usage("/app")
        cap["disk_total_gb"] = round(total / 1024**3, 1)
        cap["disk_used_gb"] = round(used / 1024**3, 1)
        cap["disk_free_gb"] = round(free / 1024**3, 1)
        cap["disk_pct"] = round(used / total * 100, 1)
    except Exception:
        cap["disk_pct"] = 0

    # ─── PostgreSQL ────────────────────────────────────────────────
    try:
        row = db.execute(text(
            "SELECT count(*) as active, "
            "(SELECT setting::int FROM pg_settings WHERE name='max_connections') as max_conn "
            "FROM pg_stat_activity"
        )).first()
        cap["pg_connections"] = row[0] if row else 0
        cap["pg_max_connections"] = row[1] if row else 100
        cap["pg_conn_pct"] = round(cap["pg_connections"] / cap["pg_max_connections"] * 100, 1)
    except Exception:
        cap["pg_connections"] = 0
        cap["pg_max_connections"] = 50
        cap["pg_conn_pct"] = 0

    try:
        row = db.execute(text("SELECT pg_database_size('reddit_saas')")).first()
        cap["pg_size_mb"] = round(row[0] / 1024 / 1024, 1) if row else 0
    except Exception:
        cap["pg_size_mb"] = 0
        try:
            db.rollback()
        except Exception:
            pass

    # ─── Redis ─────────────────────────────────────────────────────
    try:
        import redis as redis_lib
        from app.config import get_settings
        r = redis_lib.from_url(get_settings().redis_url)
        info = r.info("memory")
        cap["redis_used_mb"] = round(info.get("used_memory", 0) / 1024 / 1024, 1)
        cap["redis_max_mb"] = 192
        cap["redis_pct"] = round(cap["redis_used_mb"] / cap["redis_max_mb"] * 100, 1)
        r.close()
    except Exception:
        cap["redis_used_mb"] = 0
        cap["redis_pct"] = 0

    # ─── LLM Response Times (from ai_usage_log) ───────────────────
    try:
        row = db.execute(text("""
            SELECT 
                count(*) as calls,
                round(avg(duration_ms)::numeric, 0) as avg_ms,
                round(percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms)::numeric, 0) as p50,
                round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::numeric, 0) as p95,
                round(max(duration_ms)::numeric, 0) as max_ms
            FROM ai_usage_log 
            WHERE created_at >= now() - interval '7 days'
              AND duration_ms IS NOT NULL AND duration_ms > 0
        """)).first()
        if row and row[0] > 0:
            cap["llm_calls_7d"] = row[0]
            cap["llm_avg_ms"] = int(row[1])
            cap["llm_p50_ms"] = int(row[2])
            cap["llm_p95_ms"] = int(row[3])
            cap["llm_max_ms"] = int(row[4])
        else:
            cap["llm_calls_7d"] = 0
    except Exception:
        cap["llm_calls_7d"] = 0
        try:
            db.rollback()
        except Exception:
            pass

    # ─── LLM Top Slow Operations ──────────────────────────────────
    try:
        rows = db.execute(text("""
            SELECT operation,
                round(avg(duration_ms)::numeric, 0) as avg_ms,
                round(max(duration_ms)::numeric, 0) as max_ms,
                count(*) as cnt
            FROM ai_usage_log
            WHERE created_at >= now() - interval '7 days'
              AND duration_ms IS NOT NULL AND duration_ms > 0
            GROUP BY operation
            HAVING count(*) >= 5
            ORDER BY avg(duration_ms) DESC
            LIMIT 5
        """)).fetchall()
        cap["llm_slow_ops"] = [
            {"op": r[0], "avg_ms": int(r[1]), "max_ms": int(r[2]), "cnt": r[3]}
            for r in rows
        ]
    except Exception:
        cap["llm_slow_ops"] = []
        try:
            db.rollback()
        except Exception:
            pass

    # ─── Uptime ────────────────────────────────────────────────────
    try:
        with open("/proc/uptime") as f:
            uptime_sec = float(f.read().split()[0])
        cap["uptime_days"] = round(uptime_sec / 86400, 1)
    except Exception:
        cap["uptime_days"] = 0

    return cap


def _collect_system_health_data(db) -> dict:
    """Collect all data needed for system health report."""
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.models.comment_draft import CommentDraft
    from app.models.ai_usage import AIUsageLog
    from app.models.activity_event import ActivityEvent
    from app.models.epg_slot import EPGSlot
    from app.models.subreddit import Subreddit, ClientSubredditAssignment
    from app.services.alert_aggregation import get_system_alerts
    from sqlalchemy import func as sa_func
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # Avatar Fleet
    total_avatars = db.query(sa_func.count(Avatar.id)).filter(Avatar.active == True).scalar() or 0
    frozen_avatars = db.query(sa_func.count(Avatar.id)).filter(
        Avatar.active == True, Avatar.is_frozen == True).scalar() or 0
    shadowbanned = db.query(sa_func.count(Avatar.id)).filter(
        Avatar.active == True, Avatar.is_shadowbanned == True).scalar() or 0

    # Pipeline — this week vs last week
    gen_this = db.query(sa_func.count(CommentDraft.id)).filter(
        CommentDraft.created_at >= week_ago).scalar() or 0
    gen_last = db.query(sa_func.count(CommentDraft.id)).filter(
        CommentDraft.created_at >= two_weeks_ago, CommentDraft.created_at < week_ago).scalar() or 0
    post_this = db.query(sa_func.count(CommentDraft.id)).filter(
        CommentDraft.status == "posted", CommentDraft.posted_at >= week_ago).scalar() or 0
    post_last = db.query(sa_func.count(CommentDraft.id)).filter(
        CommentDraft.status == "posted", CommentDraft.posted_at >= two_weeks_ago,
        CommentDraft.posted_at < week_ago).scalar() or 0
    approved_this = db.query(sa_func.count(CommentDraft.id)).filter(
        CommentDraft.status.in_(["approved", "posted"]), CommentDraft.created_at >= week_ago).scalar() or 0
    slots_this = db.query(sa_func.count(EPGSlot.id)).filter(
        EPGSlot.created_at >= week_ago).scalar() or 0

    # AI Costs
    cost_this = float(db.query(sa_func.sum(AIUsageLog.cost_usd)).filter(
        AIUsageLog.created_at >= week_ago).scalar() or Decimal("0"))
    cost_last = float(db.query(sa_func.sum(AIUsageLog.cost_usd)).filter(
        AIUsageLog.created_at >= two_weeks_ago, AIUsageLog.created_at < week_ago).scalar() or Decimal("0"))
    calls_this = db.query(sa_func.count(AIUsageLog.id)).filter(
        AIUsageLog.created_at >= week_ago).scalar() or 0
    calls_last = db.query(sa_func.count(AIUsageLog.id)).filter(
        AIUsageLog.created_at >= two_weeks_ago, AIUsageLog.created_at < week_ago).scalar() or 0

    top_ops = db.query(AIUsageLog.operation, sa_func.sum(AIUsageLog.cost_usd)).filter(
        AIUsageLog.created_at >= week_ago).group_by(AIUsageLog.operation).order_by(
        sa_func.sum(AIUsageLog.cost_usd).desc()).limit(5).all()

    # Errors
    err_this = db.query(sa_func.count(ActivityEvent.id)).filter(
        ActivityEvent.created_at >= week_ago,
        ActivityEvent.event_type.in_(["error", "task_failure", "pipeline_error"])).scalar() or 0
    err_last = db.query(sa_func.count(ActivityEvent.id)).filter(
        ActivityEvent.created_at >= two_weeks_ago, ActivityEvent.created_at < week_ago,
        ActivityEvent.event_type.in_(["error", "task_failure", "pipeline_error"])).scalar() or 0

    # Scraping
    active_subs = db.query(sa_func.count(Subreddit.id)).join(ClientSubredditAssignment).filter(
        Subreddit.is_active == True, ClientSubredditAssignment.is_active == True).scalar() or 0
    stale_threshold = now - timedelta(hours=12)
    stale_subs = db.query(sa_func.count(Subreddit.id)).join(ClientSubredditAssignment).filter(
        Subreddit.is_active == True, ClientSubredditAssignment.is_active == True,
        sa_func.coalesce(Subreddit.last_scraped_at, datetime(2020, 1, 1, tzinfo=timezone.utc)) < stale_threshold
    ).scalar() or 0

    # Clients
    active_clients = db.query(sa_func.count(Client.id)).filter(Client.is_active == True).scalar() or 0

    # Alerts
    alerts = get_system_alerts(db)

    # ─── Infrastructure Capacity (from /proc + disk + PG) ──────────
    capacity = _collect_capacity_metrics(db)

    return {
        "now": now, "week_ago": week_ago,
        "total_avatars": total_avatars, "frozen_avatars": frozen_avatars,
        "shadowbanned": shadowbanned, "healthy_avatars": total_avatars - frozen_avatars,
        "gen_this": gen_this, "gen_last": gen_last,
        "post_this": post_this, "post_last": post_last,
        "approved_this": approved_this, "slots_this": slots_this,
        "cost_this": cost_this, "cost_last": cost_last,
        "calls_this": calls_this, "calls_last": calls_last,
        "top_ops": top_ops,
        "err_this": err_this, "err_last": err_last,
        "active_subs": active_subs, "stale_subs": stale_subs,
        "active_clients": active_clients, "alerts": alerts,
        "capacity": capacity,
    }


def _delta_str(current, previous) -> str:
    """Format WoW delta as string."""
    if previous == 0:
        return "—" if current == 0 else f"+{current}"
    delta = current - previous
    pct = delta / previous * 100
    sign = "+" if delta >= 0 else ""
    if isinstance(current, float):
        return f"{sign}{delta:.2f} ({sign}{pct:.0f}%)"
    return f"{sign}{delta} ({sign}{pct:.0f}%)"


def _format_system_health_email(d: dict) -> tuple[str, str, str]:
    """Format the system health email. Returns (subject, body_text, body_html)."""
    alerts = d["alerts"]
    total_avatars = d["total_avatars"]
    healthy = d["healthy_avatars"]
    frozen = d["frozen_avatars"]
    shadow = d["shadowbanned"]

    # Verdict
    critical_alerts = [a for a in alerts if a.severity == "critical"]
    high_alerts = [a for a in alerts if a.severity == "high"]
    if critical_alerts:
        verdict, emoji = "CRITICAL", "🔴"
    elif high_alerts or (total_avatars > 0 and frozen / total_avatars > 0.3):
        verdict, emoji = "DEGRADED", "🟡"
    else:
        verdict, emoji = "HEALTHY", "🟢"

    # Deltas
    gen_d = _delta_str(d["gen_this"], d["gen_last"])
    post_d = _delta_str(d["post_this"], d["post_last"])
    cost_d = _delta_str(round(d["cost_this"], 2), round(d["cost_last"], 2))
    calls_d = _delta_str(d["calls_this"], d["calls_last"])
    err_d = _delta_str(d["err_this"], d["err_last"])

    conversion = round(d["post_this"] / d["gen_this"] * 100, 1) if d["gen_this"] else 0
    cost_per_draft = round(d["cost_this"] / d["gen_this"], 4) if d["gen_this"] else 0
    daily_avg = d["cost_this"] / 7

    # Predictions
    predictions = []
    cap = d.get("capacity", {})
    if d["cost_this"] > 0 and d["cost_last"] > 0:
        trend = d["cost_this"] / d["cost_last"]
        proj = round(d["cost_this"] * trend, 2)
        if trend > 1.2:
            predictions.append(f"⚠️ AI cost growing {(trend-1)*100:.0f}%/wk → projected ${proj:.2f} next week")
        elif trend < 0.8:
            predictions.append(f"📉 AI cost declining → projected ${proj:.2f} next week")
    monthly_proj = round(daily_avg * 30, 2)
    predictions.append(f"📊 Monthly cost projection: ${monthly_proj:.2f} (${daily_avg:.2f}/day)")
    if total_avatars > 0 and frozen / total_avatars > 0.3:
        predictions.append(f"🔴 {frozen}/{total_avatars} frozen ({frozen/total_avatars*100:.0f}%) — capacity degraded")
    if d["gen_last"] > 0:
        gt = d["gen_this"] / d["gen_last"]
        if gt < 0.7:
            predictions.append(f"🔴 Generation dropped {(1-gt)*100:.0f}% WoW")
        elif gt > 1.3:
            predictions.append(f"📈 Generation up {(gt-1)*100:.0f}% WoW")
    # Capacity-based predictions
    if cap.get("mem_pct", 0) > 80:
        predictions.append(f"🔴 Memory at {cap['mem_pct']}% — OOM risk, consider upgrading droplet")
    elif cap.get("mem_pct", 0) > 65:
        predictions.append(f"🟡 Memory at {cap['mem_pct']}% — approaching limit with current load")
    if cap.get("disk_pct", 0) > 70:
        predictions.append(f"⚠️ Disk at {cap['disk_pct']}% — {cap.get('disk_free_gb', 0)}GB free, plan cleanup")
    if cap.get("pg_size_mb", 0) > 500:
        predictions.append(f"📊 DB size {cap['pg_size_mb']}MB — consider archival or Managed DB migration")
    if cap.get("cpu_pct", 0) > 70:
        predictions.append(f"🟡 CPU load {cap.get('cpu_load_5', 0):.1f}/{cap['cpu_cores']} cores — sustained high load")

    # Alert lines
    alert_lines = []
    for a in alerts[:8]:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(a.severity, "⚪")
        alert_lines.append(f"  {icon} {a.message}")

    top_ops_lines = [f"  • {op}: ${float(c):.3f}" for op, c in d["top_ops"]]

    subject = f"{emoji} Weekly System: {verdict} | {d['post_this']} posted, ${d['cost_this']:.2f} AI cost"

    # Capacity bar helper
    def _bar(pct):
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled) + f" {pct:.0f}%"

    # LLM latency section
    llm_latency_text = ""
    if cap.get("llm_calls_7d", 0) > 0:
        llm_latency_text = f"""
LLM Response Times ({cap['llm_calls_7d']} calls):
  avg={cap.get('llm_avg_ms', 0)/1000:.1f}s | p50={cap.get('llm_p50_ms', 0)/1000:.1f}s | p95={cap.get('llm_p95_ms', 0)/1000:.1f}s | max={cap.get('llm_max_ms', 0)/1000:.1f}s"""
        slow_ops = cap.get("llm_slow_ops", [])
        if slow_ops:
            llm_latency_text += "\n  Slowest operations:"
            for op in slow_ops[:4]:
                llm_latency_text += f"\n    {op['op']:28s} avg={op['avg_ms']/1000:.1f}s  max={op['max_ms']/1000:.1f}s  ({op['cnt']} calls)"

    body_text = f"""RAMP Weekly System Report
{'═' * 50}
{emoji} {verdict} | {d['week_ago'].strftime('%b %d')} – {d['now'].strftime('%b %d, %Y')} | uptime: {cap.get('uptime_days', 0):.0f} days

━━ SERVER CAPACITY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CPU:     {_bar(cap.get('cpu_pct', 0))}  (load {cap.get('cpu_load_1', 0):.2f}/{cap.get('cpu_load_5', 0):.2f}/{cap.get('cpu_load_15', 0):.2f} on {cap.get('cpu_cores', 2)} cores)
Memory:  {_bar(cap.get('mem_pct', 0))}  ({cap.get('mem_used_mb', 0)}MB / {cap.get('mem_total_mb', 0)}MB, {cap.get('mem_available_mb', 0)}MB free)
Disk:    {_bar(cap.get('disk_pct', 0))}  ({cap.get('disk_used_gb', 0)}G / {cap.get('disk_total_gb', 0)}G, {cap.get('disk_free_gb', 0)}G free)
PG Conn: {_bar(cap.get('pg_conn_pct', 0))}  ({cap.get('pg_connections', 0)} / {cap.get('pg_max_connections', 50)})
PG Size: {cap.get('pg_size_mb', 0)} MB
Redis:   {_bar(cap.get('redis_pct', 0))}  ({cap.get('redis_used_mb', 0)}MB / {cap.get('redis_max_mb', 192)}MB)
{llm_latency_text}

━━ INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Avatars: {healthy} healthy / {frozen} frozen / {shadow} shadowbanned ({total_avatars} total)
Scraping: {d['active_subs']} subs, {d['stale_subs']} stale (>12h)
Errors: {d['err_this']} this week (WoW: {err_d})
Clients: {d['active_clients']} active

━━ PIPELINE (WoW) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generated:  {d['gen_this']:>5}  (was {d['gen_last']}, {gen_d})
Posted:     {d['post_this']:>5}  (was {d['post_last']}, {post_d})
Approved:   {d['approved_this']:>5}
Conversion: {conversion}%
EPG slots:  {d['slots_this']}

━━ AI COSTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spent:      ${d['cost_this']:.2f}  (WoW: {cost_d})
Calls:      {d['calls_this']}  (WoW: {calls_d})
$/draft:    ${cost_per_draft:.4f}
Daily avg:  ${daily_avg:.2f}
Top ops:
{chr(10).join(top_ops_lines)}

━━ PREDICTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{chr(10).join(f'  {p}' for p in predictions)}

━━ ALERTS ({len(alerts)}) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{chr(10).join(alert_lines) if alert_lines else '  ✅ No active alerts'}

— RAMP Ops · gorampit.com/admin/daily-review
"""

    # HTML
    # Build alert HTML properly
    a_html = ""
    for a in alerts[:8]:
        ic = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(a.severity, "⚪")
        a_html += f"<li>{ic} {a.message}</li>"
    pred_html = "".join(f"<li>{p}</li>" for p in predictions)
    ops_summary = ", ".join(f"{op} ${float(c):.2f}" for op, c in d["top_ops"][:3])

    err_color = "#ef4444" if d["err_this"] > d["err_last"] else "#22c55e"
    cost_color = "#ef4444" if d["cost_this"] > d["cost_last"] else "#22c55e"

    body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:650px;margin:0 auto;padding:20px;color:#1e293b">
<h2 style="margin-bottom:4px">Weekly System Report</h2>
<p style="margin-top:0;font-size:20px">{emoji} {verdict} <span style="font-size:13px;color:#64748b">{d['week_ago'].strftime('%b %d')} – {d['now'].strftime('%b %d')}</span></p>

<h3 style="border-bottom:2px solid #e2e8f0;padding-bottom:4px">🖥️ Infrastructure</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<tr style="background:#f8fafc">
<td style="padding:10px;border:1px solid #e2e8f0"><b>Avatars</b><br>{healthy} healthy / {frozen} frozen / {shadow} sb</td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>Scraping</b><br>{d['active_subs']} subs, {d['stale_subs']} stale</td>
</tr><tr style="background:#f8fafc">
<td style="padding:10px;border:1px solid #e2e8f0"><b>Errors</b><br>{d['err_this']} <span style="color:{err_color}">({err_d})</span></td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>Clients</b><br>{d['active_clients']} active</td>
</tr></table>

<h3 style="border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:16px">📊 Pipeline (WoW)</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<thead><tr style="background:#f1f5f9"><th style="padding:6px;text-align:left">Metric</th><th style="padding:6px;text-align:right">This</th><th style="padding:6px;text-align:right">Last</th><th style="padding:6px;text-align:right">Δ</th></tr></thead>
<tr><td style="padding:5px">Generated</td><td style="text-align:right">{d['gen_this']}</td><td style="text-align:right;color:#64748b">{d['gen_last']}</td><td style="text-align:right">{gen_d}</td></tr>
<tr><td style="padding:5px">Posted</td><td style="text-align:right">{d['post_this']}</td><td style="text-align:right;color:#64748b">{d['post_last']}</td><td style="text-align:right">{post_d}</td></tr>
<tr><td style="padding:5px">Conversion</td><td style="text-align:right">{conversion}%</td><td colspan="2"></td></tr>
<tr><td style="padding:5px">EPG Slots</td><td style="text-align:right">{d['slots_this']}</td><td colspan="2"></td></tr>
</table>

<h3 style="border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:16px">💰 AI Costs</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<tr style="background:#f8fafc">
<td style="padding:10px;border:1px solid #e2e8f0"><b>Spent</b><br><span style="font-size:18px">${d['cost_this']:.2f}</span> <span style="font-size:11px;color:{cost_color}">({cost_d})</span></td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>Calls</b><br>{d['calls_this']} ({calls_d})</td>
</tr><tr style="background:#f8fafc">
<td style="padding:10px;border:1px solid #e2e8f0"><b>$/draft</b><br>${cost_per_draft:.4f}</td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>Daily avg</b><br>${daily_avg:.2f}</td>
</tr></table>
<p style="font-size:11px;color:#64748b;margin:4px 0">Top: {ops_summary}</p>

<h3 style="border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:16px">⚡ Response Times</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<tr style="background:#f8fafc">
<td style="padding:10px;border:1px solid #e2e8f0"><b>LLM avg</b><br>{cap.get('llm_avg_ms', 0)/1000:.1f}s</td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>p50</b><br>{cap.get('llm_p50_ms', 0)/1000:.1f}s</td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>p95</b><br><span style="color:{'#ef4444' if cap.get('llm_p95_ms', 0) > 30000 else '#1e293b'}">{cap.get('llm_p95_ms', 0)/1000:.1f}s</span></td>
<td style="padding:10px;border:1px solid #e2e8f0"><b>max</b><br><span style="color:#ef4444">{cap.get('llm_max_ms', 0)/1000:.1f}s</span></td>
</tr></table>

<h3 style="border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:16px">🔮 Predictions</h3>
<ul style="padding-left:16px;font-size:13px">{pred_html if pred_html else '<li style="color:#22c55e">All stable</li>'}</ul>

<h3 style="border-bottom:2px solid #e2e8f0;padding-bottom:4px;margin-top:16px">🚨 Alerts ({len(alerts)})</h3>
<ul style="padding-left:16px;font-size:13px">{a_html if a_html else '<li style="color:#22c55e">✅ None</li>'}</ul>

<div style="margin-top:20px"><a href="https://gorampit.com/admin/daily-review" style="background:#1e293b;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">Open Ops Review</a></div>
<p style="color:#94a3b8;font-size:11px;margin-top:20px">RAMP Ops Agent — automated weekly</p>
</div>"""

    return subject, body_text, body_html


def send_weekly_system_health_report() -> bool:
    """Send weekly system health digest to owner/admin.

    Content: infrastructure status, load dynamics (7-day trends with WoW delta),
    pipeline throughput, AI cost analysis, avatar fleet, predictive signals.
    """
    from app.database import SessionLocal
    from app.services.alert_aggregation import get_system_alerts
    from app.services.email_sender import send_task_email

    recipients = _get_owner_emails()
    if not recipients:
        return False

    db = SessionLocal()
    try:
        data = _collect_system_health_data(db)
        subject, body_text, body_html = _format_system_health_email(data)

        sent = 0
        for email in recipients:
            success, _ = send_task_email(email, subject, body_text, body_html)
            if success:
                sent += 1
        if sent:
            logger.info("Weekly system health report sent to %d recipients", sent)
        return sent > 0
    except Exception as e:
        logger.warning("Failed to send weekly system health report: %s", e)
        return False
    finally:
        db.close()


# ─── 5. Weekly Business Summary (Partners) ────────────────────────────────────


def send_weekly_business_summary() -> bool:
    """Send weekly business summary to partners.

    Content: MRR, active clients, trial funnel, AI spend, margin,
    per-client health table, attention items.

    Triggered: Sunday evening (scheduled via Beat or manual).
    """
    from app.database import SessionLocal
    from app.services.business_metrics import (
        get_business_metrics,
        get_client_health_table,
        get_trial_funnel,
        get_attention_items,
        PLAN_PRICES,
    )
    from app.services.email_sender import send_task_email

    recipients = _get_partner_emails()
    if not recipients:
        # Fallback: send to owners too if no dedicated partners
        recipients = _get_owner_emails()
    if not recipients:
        logger.debug("No partner/owner emails for business summary")
        return False

    db = SessionLocal()
    try:
        metrics = get_business_metrics(db)
        health_table = get_client_health_table(db)
        trial_funnel = get_trial_funnel(db)
        attention = get_attention_items(db)

        mrr = metrics["mrr"]
        paying = metrics["active_paying"]
        trials = metrics["active_trials"]
        ai_spend = metrics["ai_spend_month"]
        margin = metrics["margin_pct"]

        # Client health summary
        red_clients = [c for c in health_table if c["health"] == "red"]
        yellow_clients = [c for c in health_table if c["health"] == "yellow"]
        green_clients = [c for c in health_table if c["health"] == "green"]

        # Attention items
        attention_lines = []
        for item in attention[:6]:
            attention_lines.append(f"  {item.get('icon', '•')} {item['message']}")

        # Client table lines
        client_lines = []
        for c in health_table[:10]:
            health_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(c["health"], "⚪")
            trial_tag = f" (trial, {c['trial_days_left']}d left)" if c["is_trial"] else ""
            client_lines.append(
                f"  {health_icon} {c['client_name']}{trial_tag} — "
                f"{c['posts_week']} posted, {c['avatars_active']} avatars"
            )

        subject = f"💼 Weekly Business: ${mrr:,}/mo MRR, {paying} paying, {trials} trials"

        body_text = f"""RAMP Weekly Business Summary
{'=' * 40}

Revenue:
  • MRR: ${mrr:,}/mo
  • Paying clients: {paying}
  • Active trials: {trials}
  • AI spend (MTD): ${ai_spend:.2f}
  • Margin: {margin}%

Client Health:
  🟢 {len(green_clients)} healthy | 🟡 {len(yellow_clients)} warning | 🔴 {len(red_clients)} critical

{chr(10).join(client_lines)}

Trial Funnel:
  • Active: {trial_funnel['active_trials']}
  • Onboarded: {trial_funnel['onboarding_complete']}
  • First draft: {trial_funnel['first_draft_generated']}
  • Converted: {trial_funnel['converted']}

{f"Attention Items:{chr(10)}{chr(10).join(attention_lines)}" if attention_lines else "✅ No attention items"}

—
RAMP Business Intelligence — gorampit.com/admin
"""

        # HTML version
        client_rows_html = ""
        for c in health_table[:10]:
            health_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}.get(c["health"], "⚪")
            trial_badge = '<span style="background:#dbeafe;color:#1d4ed8;padding:2px 6px;border-radius:4px;font-size:11px">trial</span>' if c["is_trial"] else ""
            client_rows_html += f"""<tr>
<td style="padding:8px;border-bottom:1px solid #e2e8f0">{health_icon} {c['client_name']} {trial_badge}</td>
<td style="padding:8px;border-bottom:1px solid #e2e8f0;text-align:center">{c['posts_week']}</td>
<td style="padding:8px;border-bottom:1px solid #e2e8f0;text-align:center">{c['avatars_active']}</td>
<td style="padding:8px;border-bottom:1px solid #e2e8f0;text-align:center">{c.get('generated_week', 0)}</td>
</tr>"""

        attention_html = "".join(
            f'<li>{item.get("icon", "•")} {item["message"]}</li>'
            for item in attention[:6]
        )

        body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px">
<h2 style="margin-bottom:5px">Weekly Business Summary</h2>

<div style="display:flex;gap:12px;flex-wrap:wrap;margin:16px 0">
  <div style="background:#f0fdf4;border-radius:8px;padding:12px 16px;flex:1;min-width:120px">
    <div style="font-size:11px;color:#666">MRR</div>
    <div style="font-size:22px;font-weight:bold;color:#166534">${mrr:,}</div>
  </div>
  <div style="background:#eff6ff;border-radius:8px;padding:12px 16px;flex:1;min-width:120px">
    <div style="font-size:11px;color:#666">Paying</div>
    <div style="font-size:22px;font-weight:bold;color:#1d4ed8">{paying}</div>
  </div>
  <div style="background:#fef3c7;border-radius:8px;padding:12px 16px;flex:1;min-width:120px">
    <div style="font-size:11px;color:#666">Trials</div>
    <div style="font-size:22px;font-weight:bold;color:#92400e">{trials}</div>
  </div>
  <div style="background:#f8fafc;border-radius:8px;padding:12px 16px;flex:1;min-width:120px">
    <div style="font-size:11px;color:#666">Margin</div>
    <div style="font-size:22px;font-weight:bold">{margin}%</div>
  </div>
</div>

<h3>Client Health</h3>
<p>🟢 {len(green_clients)} healthy &nbsp; 🟡 {len(yellow_clients)} warning &nbsp; 🔴 {len(red_clients)} critical</p>

<table style="width:100%;border-collapse:collapse;font-size:13px;margin:12px 0">
<thead><tr style="background:#f1f5f9">
  <th style="padding:8px;text-align:left">Client</th>
  <th style="padding:8px;text-align:center">Posted</th>
  <th style="padding:8px;text-align:center">Avatars</th>
  <th style="padding:8px;text-align:center">Generated</th>
</tr></thead>
<tbody>{client_rows_html}</tbody>
</table>

<h3>Trial Funnel</h3>
<div style="background:#f8fafc;border-radius:8px;padding:12px 16px;margin:12px 0;font-size:13px">
  Active: {trial_funnel['active_trials']} → Onboarded: {trial_funnel['onboarding_complete']} → First draft: {trial_funnel['first_draft_generated']} → Converted: {trial_funnel['converted']}
</div>

{f'<h3>⚠️ Needs Attention</h3><ul style="padding-left:20px">{attention_html}</ul>' if attention else '<p style="color:#22c55e">✅ No attention items this week</p>'}

<div style="margin-top:24px">
  <a href="https://gorampit.com/admin/" style="background:#1e293b;color:white;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">Open Dashboard</a>
</div>

<p style="color:#888;font-size:12px;margin-top:24px">RAMP Business Intelligence — Weekly Digest</p>
</div>"""

        sent = 0
        for email in recipients:
            success, _ = send_task_email(email, subject, body_text, body_html)
            if success:
                sent += 1

        if sent:
            logger.info("Weekly business summary sent to %d recipients", sent)
        return sent > 0

    except Exception as e:
        logger.warning("Failed to send weekly business summary: %s", e)
        return False
    finally:
        db.close()
