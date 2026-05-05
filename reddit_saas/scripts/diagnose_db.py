#!/usr/bin/env python3
"""
Database Diagnostic Script — проверяет целостность и актуальность данных.

Запуск:
    cd reddit_saas && python -m scripts.diagnose_db

Выводит:
    ✅ — проверка пройдена
    ⚠️  — предупреждение (не критично, но стоит обратить внимание)
    ❌ — проблема (нужно исправить)

В конце — итоговый статус: HEALTHY / WARNINGS / CRITICAL
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Add parent dir so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text, func, inspect
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base
from app.models.user import User
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.subreddit import ClientSubreddit
from app.models.thread import RedditThread
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.ai_usage import AIUsageLog
from app.models.audit import AuditLog
from app.models.settings import SystemSetting
from app.models.hobby import HobbySubreddit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DiagResult:
    def __init__(self):
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def ok(self, msg: str):
        self.passed.append(msg)
        print(f"  ✅ {msg}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"  ⚠️  {msg}")

    def fail(self, msg: str):
        self.errors.append(msg)
        print(f"  ❌ {msg}")

    def check(self, condition: bool, ok_msg: str, fail_msg: str):
        if condition:
            self.ok(ok_msg)
        else:
            self.fail(fail_msg)

    def check_warn(self, condition: bool, ok_msg: str, warn_msg: str):
        if condition:
            self.ok(ok_msg)
        else:
            self.warn(warn_msg)

    @property
    def status(self) -> str:
        if self.errors:
            return "CRITICAL"
        if self.warnings:
            return "WARNINGS"
        return "HEALTHY"


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Diagnostic checks
# ---------------------------------------------------------------------------

def check_connection(db: Session, diag: DiagResult):
    """Check database connectivity and basic info."""
    section("1. DATABASE CONNECTION")
    try:
        result = db.execute(text("SELECT version()")).scalar()
        diag.ok(f"PostgreSQL connected: {result[:60]}...")

        result = db.execute(text("SELECT current_database()")).scalar()
        diag.ok(f"Database: {result}")

        # DB size
        size = db.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database()))"
        )).scalar()
        diag.ok(f"Database size: {size}")

        # Active connections
        conns = db.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )).scalar()
        diag.check_warn(conns < 50, f"Active connections: {conns}", f"High connection count: {conns}")

    except Exception as e:
        diag.fail(f"Cannot connect to database: {e}")


def check_tables_exist(db: Session, diag: DiagResult):
    """Verify all expected tables exist."""
    section("2. TABLE EXISTENCE")
    inspector = inspect(db.bind)
    existing_tables = set(inspector.get_table_names())

    expected_tables = [
        "users", "clients", "avatars", "client_subreddits",
        "reddit_threads", "comment_drafts", "post_drafts",
        "ai_usage_log", "audit_log", "system_settings", "hobby_subreddits",
        "alembic_version",
    ]

    for table in expected_tables:
        diag.check(
            table in existing_tables,
            f"Table '{table}' exists",
            f"Table '{table}' MISSING"
        )

    extra = existing_tables - set(expected_tables)
    if extra:
        diag.warn(f"Unknown tables found: {extra}")


def check_row_counts(db: Session, diag: DiagResult) -> dict:
    """Count rows in all tables and report."""
    section("3. ROW COUNTS")
    counts = {}

    tables = [
        ("users", User),
        ("clients", Client),
        ("avatars", Avatar),
        ("client_subreddits", ClientSubreddit),
        ("reddit_threads", RedditThread),
        ("comment_drafts", CommentDraft),
        ("post_drafts", PostDraft),
        ("ai_usage_log", AIUsageLog),
        ("audit_log", AuditLog),
        ("system_settings", SystemSetting),
        ("hobby_subreddits", HobbySubreddit),
    ]

    for name, model in tables:
        try:
            count = db.query(func.count(model.id)).scalar() or 0
            counts[name] = count
            print(f"  📊 {name}: {count} rows")
        except Exception as e:
            diag.fail(f"Cannot count {name}: {e}")
            counts[name] = -1

    # Basic sanity
    diag.check(counts.get("users", 0) > 0, "At least 1 user exists", "NO USERS in database — system unusable")
    diag.check_warn(counts.get("clients", 0) > 0, "At least 1 client exists", "No clients — nothing to process")
    diag.check_warn(counts.get("avatars", 0) > 0, "At least 1 avatar exists", "No avatars — cannot post comments")

    return counts


def check_users(db: Session, diag: DiagResult):
    """Check user data integrity."""
    section("4. USERS")

    total = db.query(func.count(User.id)).scalar() or 0
    active = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    superusers = db.query(func.count(User.id)).filter(User.is_superuser.is_(True)).scalar() or 0
    active_superusers = db.query(func.count(User.id)).filter(
        User.is_active.is_(True), User.is_superuser.is_(True)
    ).scalar() or 0

    print(f"  📊 Total: {total}, Active: {active}, Superusers: {superusers}")

    diag.check(active_superusers > 0, f"{active_superusers} active superuser(s)", "NO active superusers — admin panel inaccessible")
    diag.check_warn(active > 0, f"{active} active user(s)", "No active users")

    # Check for duplicate emails
    dupes = db.execute(text(
        "SELECT email, count(*) FROM users GROUP BY email HAVING count(*) > 1"
    )).fetchall()
    diag.check(len(dupes) == 0, "No duplicate emails", f"DUPLICATE EMAILS: {[d[0] for d in dupes]}")


def check_clients(db: Session, diag: DiagResult):
    """Check client data integrity and completeness."""
    section("5. CLIENTS")

    clients = db.query(Client).filter(Client.is_active.is_(True)).all()
    print(f"  📊 Active clients: {len(clients)}")

    for c in clients:
        prefix = f"[{c.client_name}]"

        # Profile completeness
        profile_fields = [
            ("company_profile", c.company_profile),
            ("company_worldview", c.company_worldview),
            ("company_problem", c.company_problem),
            ("brand_voice", c.brand_voice),
            ("icp_profiles", c.icp_profiles),
        ]
        empty_fields = [name for name, val in profile_fields if not val or not val.strip()]
        if empty_fields:
            diag.warn(f"{prefix} Empty profile fields: {empty_fields}")
        else:
            diag.ok(f"{prefix} All profile fields populated")

        # Keywords
        kw = c.keywords or {}
        total_kw = sum(len(v) for v in kw.values() if isinstance(v, list))
        diag.check_warn(total_kw > 0, f"{prefix} {total_kw} keywords configured", f"{prefix} NO keywords — scoring will be weak")

        # Check keyword structure
        if kw:
            valid_priorities = {"high", "medium", "low"}
            bad_keys = set(kw.keys()) - valid_priorities
            if bad_keys:
                diag.fail(f"{prefix} Invalid keyword priority keys: {bad_keys}")
            else:
                diag.ok(f"{prefix} Keyword structure valid (high/medium/low)")

        # Subreddits
        subs = db.query(func.count(ClientSubreddit.id)).filter(
            ClientSubreddit.client_id == c.id,
            ClientSubreddit.is_active.is_(True)
        ).scalar() or 0
        diag.check_warn(subs > 0, f"{prefix} {subs} active subreddits", f"{prefix} NO subreddits — nothing to scrape")

        # Avatars assigned
        avatars = db.query(Avatar).filter(
            Avatar.active.is_(True),
            Avatar.client_ids.any(str(c.id))
        ).count()
        diag.check_warn(avatars > 0, f"{prefix} {avatars} avatar(s) assigned", f"{prefix} NO avatars assigned — cannot post")


def check_avatars(db: Session, diag: DiagResult):
    """Check avatar health and configuration."""
    section("6. AVATARS")

    avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    print(f"  📊 Active avatars: {len(avatars)}")

    for a in avatars:
        prefix = f"[@{a.reddit_username}]"

        # Voice profile
        diag.check_warn(
            bool(a.voice_profile_md and a.voice_profile_md.strip()),
            f"{prefix} Voice profile set",
            f"{prefix} NO voice profile — AI generation quality will suffer"
        )

        # Client assignments
        client_count = len(a.client_ids) if a.client_ids else 0
        diag.check_warn(client_count > 0, f"{prefix} Assigned to {client_count} client(s)", f"{prefix} Not assigned to any client")

        # Shadowban check
        if a.is_shadowbanned:
            diag.fail(f"{prefix} SHADOWBANNED — comments won't be visible")

        # Health check freshness
        if a.last_health_check:
            age = datetime.now(timezone.utc) - a.last_health_check.replace(tzinfo=timezone.utc) if a.last_health_check.tzinfo is None else datetime.now(timezone.utc) - a.last_health_check
            if age > timedelta(days=7):
                diag.warn(f"{prefix} Health check stale ({age.days} days ago)")
            else:
                diag.ok(f"{prefix} Health check recent ({age.days}d ago)")
        else:
            diag.warn(f"{prefix} Never health-checked")


def check_threads(db: Session, diag: DiagResult):
    """Check thread data freshness and scoring."""
    section("7. THREADS & SCORING")

    total = db.query(func.count(RedditThread.id)).scalar() or 0
    print(f"  📊 Total threads: {total}")

    if total == 0:
        diag.warn("No threads scraped yet — pipeline hasn't run")
        return

    # Freshness
    latest = db.query(func.max(RedditThread.scraped_at)).scalar()
    if latest:
        age = datetime.now(timezone.utc) - (latest.replace(tzinfo=timezone.utc) if latest.tzinfo is None else latest)
        diag.check_warn(
            age < timedelta(hours=24),
            f"Latest scrape: {age.total_seconds()/3600:.1f}h ago",
            f"Scraping stale — last scrape {age.days}d {age.seconds//3600}h ago"
        )

    # Scoring distribution
    tagged = db.query(RedditThread.tag, func.count(RedditThread.id)).group_by(RedditThread.tag).all()
    tag_counts = {tag or "unscored": count for tag, count in tagged}
    print(f"  📊 Tag distribution: {dict(tag_counts)}")

    unscored = tag_counts.get("unscored", 0)
    if unscored > 0:
        pct = (unscored / total) * 100
        diag.check_warn(pct < 20, f"Unscored threads: {unscored} ({pct:.0f}%)", f"{unscored} unscored threads ({pct:.0f}%) — scoring pipeline may be stuck")

    # Threads with engage tag but no comment draft
    engage_count = tag_counts.get("engage", 0)
    if engage_count > 0:
        engage_ids = db.query(RedditThread.id).filter(RedditThread.tag == "engage").subquery()
        with_draft = db.query(func.count(func.distinct(CommentDraft.thread_id))).filter(
            CommentDraft.thread_id.in_(engage_ids)
        ).scalar() or 0
        missing = engage_count - with_draft
        diag.check_warn(
            missing == 0,
            f"All {engage_count} 'engage' threads have comment drafts",
            f"{missing} 'engage' threads have NO comment draft — generation may have failed"
        )

    # Per-client thread freshness
    clients = db.query(Client).filter(Client.is_active.is_(True)).all()
    for c in clients:
        client_latest = db.query(func.max(RedditThread.scraped_at)).filter(
            RedditThread.client_id == c.id
        ).scalar()
        if client_latest:
            age = datetime.now(timezone.utc) - (client_latest.replace(tzinfo=timezone.utc) if client_latest.tzinfo is None else client_latest)
            diag.check_warn(
                age < timedelta(hours=48),
                f"[{c.client_name}] Latest thread: {age.total_seconds()/3600:.1f}h ago",
                f"[{c.client_name}] No threads in {age.days}d — scraping may be broken for this client"
            )
        else:
            diag.warn(f"[{c.client_name}] ZERO threads scraped ever")


def check_comment_drafts(db: Session, diag: DiagResult):
    """Check comment draft pipeline health."""
    section("8. COMMENT DRAFTS")

    total = db.query(func.count(CommentDraft.id)).scalar() or 0
    print(f"  📊 Total comment drafts: {total}")

    if total == 0:
        diag.warn("No comment drafts yet — generation pipeline hasn't run")
        return

    # Status distribution
    statuses = db.query(CommentDraft.status, func.count(CommentDraft.id)).group_by(CommentDraft.status).all()
    status_counts = {s: c for s, c in statuses}
    print(f"  📊 Status distribution: {dict(status_counts)}")

    pending = status_counts.get("pending", 0)
    approved = status_counts.get("approved", 0)
    rejected = status_counts.get("rejected", 0)
    posted = status_counts.get("posted", 0)

    # Pending review backlog
    if pending > 20:
        diag.warn(f"{pending} comments pending review — backlog growing")
    elif pending > 0:
        diag.ok(f"{pending} comments pending review")

    # Approved but not posted
    if approved > 10:
        diag.warn(f"{approved} approved but NOT posted — someone needs to post them")
    elif approved > 0:
        diag.ok(f"{approved} approved, ready to post")

    # Rejection rate
    reviewed = approved + rejected + posted
    if reviewed > 0:
        reject_rate = (rejected / reviewed) * 100
        diag.check_warn(
            reject_rate < 50,
            f"Rejection rate: {reject_rate:.0f}% ({rejected}/{reviewed})",
            f"HIGH rejection rate: {reject_rate:.0f}% — AI generation quality may need tuning"
        )

    # Drafts with empty content
    empty_drafts = db.query(func.count(CommentDraft.id)).filter(
        CommentDraft.ai_draft.is_(None) | (CommentDraft.ai_draft == "")
    ).scalar() or 0
    diag.check(empty_drafts == 0, "All drafts have AI content", f"{empty_drafts} drafts with EMPTY ai_draft — generation failed silently")

    # Freshness
    latest = db.query(func.max(CommentDraft.created_at)).scalar()
    if latest:
        age = datetime.now(timezone.utc) - (latest.replace(tzinfo=timezone.utc) if latest.tzinfo is None else latest)
        diag.check_warn(
            age < timedelta(hours=48),
            f"Latest draft: {age.total_seconds()/3600:.1f}h ago",
            f"No new drafts in {age.days}d {age.seconds//3600}h — generation pipeline may be stuck"
        )


def check_ai_usage(db: Session, diag: DiagResult):
    """Check AI usage and costs."""
    section("9. AI USAGE & COSTS")

    total = db.query(func.count(AIUsageLog.id)).scalar() or 0
    print(f"  📊 Total AI calls: {total}")

    if total == 0:
        diag.warn("No AI usage logged — pipeline hasn't used AI yet")
        return

    # Total cost
    total_cost = db.query(func.sum(AIUsageLog.cost_usd)).scalar() or 0
    print(f"  💰 Total cost: ${float(total_cost):.4f}")

    # Cost last 24h
    yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
    cost_24h = db.query(func.sum(AIUsageLog.cost_usd)).filter(
        AIUsageLog.created_at >= yesterday
    ).scalar() or 0
    print(f"  💰 Cost (24h): ${float(cost_24h):.4f}")

    # Cost by operation
    by_op = db.query(
        AIUsageLog.operation,
        func.count(AIUsageLog.id),
        func.sum(AIUsageLog.cost_usd)
    ).group_by(AIUsageLog.operation).all()
    for op, count, cost in by_op:
        print(f"  📊 {op}: {count} calls, ${float(cost or 0):.4f}")

    # Check for errors (zero-cost calls might indicate failures)
    zero_cost = db.query(func.count(AIUsageLog.id)).filter(
        AIUsageLog.cost_usd == 0,
        AIUsageLog.input_tokens == 0,
        AIUsageLog.output_tokens == 0
    ).scalar() or 0
    if zero_cost > 0:
        pct = (zero_cost / total) * 100
        diag.check_warn(pct < 10, f"Zero-token calls: {zero_cost} ({pct:.0f}%)", f"{zero_cost} zero-token AI calls ({pct:.0f}%) — possible API failures logged")

    # Budget check
    budget_setting = db.query(SystemSetting).filter(SystemSetting.key == "monthly_budget_usd").first()
    if budget_setting:
        try:
            budget = float(budget_setting.value)
            # Current month cost
            month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_cost = db.query(func.sum(AIUsageLog.cost_usd)).filter(
                AIUsageLog.created_at >= month_start
            ).scalar() or 0
            pct = (float(month_cost) / budget * 100) if budget > 0 else 0
            if pct > 100:
                diag.fail(f"Monthly budget EXCEEDED: ${float(month_cost):.2f} / ${budget:.2f} ({pct:.0f}%)")
            elif pct > 80:
                diag.warn(f"Monthly budget at {pct:.0f}%: ${float(month_cost):.2f} / ${budget:.2f}")
            else:
                diag.ok(f"Monthly budget: ${float(month_cost):.2f} / ${budget:.2f} ({pct:.0f}%)")
        except (ValueError, TypeError):
            diag.warn(f"Cannot parse monthly_budget setting: '{budget_setting.value}'")
    else:
        diag.warn("No monthly_budget setting configured")


def check_orphans(db: Session, diag: DiagResult):
    """Check for orphaned records (FK integrity)."""
    section("10. DATA INTEGRITY (ORPHANS)")

    # Comment drafts pointing to non-existent threads
    orphan_comments = db.execute(text("""
        SELECT count(*) FROM comment_drafts cd
        LEFT JOIN reddit_threads rt ON cd.thread_id = rt.id
        WHERE rt.id IS NULL
    """)).scalar() or 0
    diag.check(orphan_comments == 0, "No orphaned comment drafts", f"{orphan_comments} comment drafts reference missing threads")

    # Comment drafts pointing to non-existent clients
    orphan_client_comments = db.execute(text("""
        SELECT count(*) FROM comment_drafts cd
        LEFT JOIN clients c ON cd.client_id = c.id
        WHERE c.id IS NULL
    """)).scalar() or 0
    diag.check(orphan_client_comments == 0, "No comment drafts with missing client", f"{orphan_client_comments} comment drafts reference missing clients")

    # Threads pointing to non-existent clients
    orphan_threads = db.execute(text("""
        SELECT count(*) FROM reddit_threads rt
        LEFT JOIN clients c ON rt.client_id = c.id
        WHERE c.id IS NULL
    """)).scalar() or 0
    diag.check(orphan_threads == 0, "No orphaned threads", f"{orphan_threads} threads reference missing clients")

    # Subreddits pointing to non-existent clients
    orphan_subs = db.execute(text("""
        SELECT count(*) FROM client_subreddits cs
        LEFT JOIN clients c ON cs.client_id = c.id
        WHERE c.id IS NULL
    """)).scalar() or 0
    diag.check(orphan_subs == 0, "No orphaned subreddits", f"{orphan_subs} subreddits reference missing clients")

    # Duplicate reddit_native_id in threads
    dupe_threads = db.execute(text("""
        SELECT reddit_native_id, count(*) FROM reddit_threads
        GROUP BY reddit_native_id HAVING count(*) > 1
    """)).fetchall()
    diag.check(len(dupe_threads) == 0, "No duplicate thread reddit_native_ids", f"{len(dupe_threads)} duplicate reddit_native_id(s) in threads")


def check_pipeline_readiness(db: Session, diag: DiagResult):
    """Check if the system is ready to run the pipeline."""
    section("11. PIPELINE READINESS")

    from app.config import get_config

    # Reddit API
    has_reddit = bool(get_config("reddit_client_id", db) and get_config("reddit_client_secret", db))
    diag.check(has_reddit, "Reddit API credentials configured", "Reddit API credentials MISSING — scraping won't work")

    # LLM API
    has_llm = bool(get_config("llm_api_key", db))
    diag.check(has_llm, "LLM API key configured", "LLM API key MISSING — scoring and generation won't work")

    # At least one complete client setup
    clients = db.query(Client).filter(Client.is_active.is_(True)).all()
    ready_clients = 0
    for c in clients:
        has_subs = db.query(func.count(ClientSubreddit.id)).filter(
            ClientSubreddit.client_id == c.id, ClientSubreddit.is_active.is_(True)
        ).scalar() or 0
        has_avatars = db.query(Avatar).filter(
            Avatar.active.is_(True), Avatar.client_ids.any(str(c.id))
        ).count()
        kw_count = sum(len(v) for v in (c.keywords or {}).values() if isinstance(v, list))

        if has_subs > 0 and has_avatars > 0 and kw_count > 0:
            ready_clients += 1
            diag.ok(f"[{c.client_name}] Pipeline-ready (subs={has_subs}, avatars={has_avatars}, keywords={kw_count})")
        else:
            missing = []
            if has_subs == 0: missing.append("subreddits")
            if has_avatars == 0: missing.append("avatars")
            if kw_count == 0: missing.append("keywords")
            diag.warn(f"[{c.client_name}] NOT pipeline-ready — missing: {', '.join(missing)}")

    diag.check_warn(ready_clients > 0, f"{ready_clients} client(s) pipeline-ready", "No clients are fully configured for pipeline")


def check_settings(db: Session, diag: DiagResult):
    """Check system settings."""
    section("12. SYSTEM SETTINGS")

    settings_list = db.query(SystemSetting).all()
    print(f"  📊 {len(settings_list)} system settings")

    expected_keys = ["monthly_budget_usd", "aws_credits_remaining"]
    for key in expected_keys:
        found = any(s.key == key for s in settings_list)
        diag.check_warn(found, f"Setting '{key}' exists", f"Setting '{key}' not configured")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  🔍 DATABASE DIAGNOSTIC REPORT")
    print(f"  📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    settings = get_settings()
    engine = create_engine(settings.database_url)
    diag = DiagResult()

    with Session(engine) as db:
        check_connection(db, diag)
        check_tables_exist(db, diag)
        counts = check_row_counts(db, diag)
        check_users(db, diag)
        check_clients(db, diag)
        check_avatars(db, diag)
        check_threads(db, diag)
        check_comment_drafts(db, diag)
        check_ai_usage(db, diag)
        check_orphans(db, diag)
        check_pipeline_readiness(db, diag)
        check_settings(db, diag)

    # Summary
    print("\n" + "=" * 60)
    print("  📋 SUMMARY")
    print("=" * 60)
    print(f"  ✅ Passed:   {len(diag.passed)}")
    print(f"  ⚠️  Warnings: {len(diag.warnings)}")
    print(f"  ❌ Errors:   {len(diag.errors)}")
    print()

    if diag.errors:
        print("  🔴 STATUS: CRITICAL")
        print("  Errors found:")
        for e in diag.errors:
            print(f"    ❌ {e}")
    elif diag.warnings:
        print("  🟡 STATUS: WARNINGS")
        print("  Warnings:")
        for w in diag.warnings:
            print(f"    ⚠️  {w}")
    else:
        print("  🟢 STATUS: HEALTHY")

    print()
    return 1 if diag.errors else 0


if __name__ == "__main__":
    sys.exit(main())
