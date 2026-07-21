"""Bug Condition Exploration Test — Landscape Report Has Zero Observability.

**Property 1: Bug Condition** — Report Generation Has Zero Observability

This test MUST FAIL on unfixed code — failure confirms the bug exists.
DO NOT attempt to fix the test or the code when it fails.

GOAL: Surface counterexamples that demonstrate report generation creates
no tracking entities (no job records, no lifecycle events, no deduplication,
no error recording).

Scoped PBT Approach: For any valid client_id, calling generate_landscape_report()
should result in a ReportGenerationJob entity and lifecycle events — but on
unfixed code it won't.

Validates: Requirements 1.1, 1.5, 1.6
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.subreddit import Subreddit, ClientSubredditAssignment


# --- Strategies ---

st_brand_name = st.sampled_from([
    "Acme Corp", "NovaTech", "GreenLeaf", "DataPulse", "CloudSync",
    "QuantumEdge", "SilverStream", "IronGate", "BluePeak", "VividNode",
])

st_keyword_tier = st.fixed_dictionaries({
    "high": st.lists(st.sampled_from([
        "security", "monitoring", "detection", "threat", "compliance",
        "automation", "analytics", "cloud", "devops", "infrastructure",
    ]), min_size=1, max_size=4),
    "medium": st.lists(st.sampled_from([
        "platform", "solution", "enterprise", "management", "optimization",
    ]), min_size=0, max_size=3),
    "low": st.lists(st.sampled_from([
        "tool", "software", "system", "service", "product",
    ]), min_size=0, max_size=2),
})

st_competitive_landscape = st.sampled_from([
    "CompetitorA, CompetitorB, CompetitorC",
    "Rival Inc\nBigCo\nSmallFish",
    "Alpha - market leader\nBeta - challenger",
    None,
    "",
])


# --- Helpers ---

def _create_test_client(db: Session, brand_name: str, keywords: dict | None,
                        competitive_landscape: str | None) -> Client:
    """Create a test client with given configuration."""
    client = Client(
        client_name=f"TestClient_{uuid.uuid4().hex[:8]}",
        brand_name=brand_name,
        keywords=keywords,
        competitive_landscape=competitive_landscape,
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client


def _table_exists(db: Session, table_name: str) -> bool:
    """Check if a table exists in the database."""
    result = db.execute(
        text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table_name},
    )
    return result.scalar()


def _count_rows(db: Session, table_name: str, condition: str = "1=1",
                params: dict | None = None) -> int:
    """Count rows in a table with optional condition. Returns 0 if table doesn't exist."""
    if not _table_exists(db, table_name):
        return 0
    result = db.execute(text(f"SELECT COUNT(*) FROM {table_name} WHERE {condition}"),
                        params or {})
    return result.scalar()


# --- Property Tests ---


class TestBugConditionZeroObservability:
    """Property 1: Expected Behavior — Report Generation Creates Tracked Job.

    **Validates: Requirements 2.1, 2.4, 2.5, 2.6**

    These tests call generate_landscape_report_tracked() — the NEW function
    that creates jobs and emits events. The original generate_landscape_report()
    was intentionally preserved without tracking for backward compatibility.
    """

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
        competitive_landscape=st_competitive_landscape,
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_generation_should_create_job_entity(
        self, db: Session, brand_name: str, keywords: dict,
        competitive_landscape: str | None
    ):
        """For any valid client, generate_landscape_report_tracked() SHOULD create a
        ReportGenerationJob entity.

        Property: ∀ client_id valid → ∃ job ∈ report_generation_jobs
                  WHERE job.client_id = client_id
                  AND job.status ∈ ('completed', 'failed')
        """
        from app.services.onboarding.landscape_report import generate_landscape_report_tracked

        client = _create_test_client(db, brand_name, keywords, competitive_landscape)

        # Call the tracked function under test
        result = generate_landscape_report_tracked(db, client.id)

        # The function should return a result (not crash)
        assert result is not None

        # EXPECTED BEHAVIOR: A job entity should exist for this generation
        job_count = _count_rows(
            db, "report_generation_jobs",
            "client_id = :cid",
            {"cid": str(client.id)},
        )
        assert job_count >= 1, (
            f"COUNTEREXAMPLE: generate_landscape_report_tracked() completed for client "
            f"'{brand_name}' (id={client.id}) but created 0 rows in "
            f"report_generation_jobs. Expected ≥1 job entity tracking this generation."
        )

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_generation_should_emit_lifecycle_events(
        self, db: Session, brand_name: str, keywords: dict
    ):
        """For any valid client, generate_landscape_report_tracked() SHOULD emit
        lifecycle events (at minimum REPORT_STARTED + REPORT_COMPLETED/REPORT_FAILED).

        Property: ∀ client_id valid → |report_job_events WHERE job.client_id = client_id| >= 2
        """
        from app.services.onboarding.landscape_report import generate_landscape_report_tracked

        client = _create_test_client(db, brand_name, keywords, None)

        # Call the tracked function under test
        generate_landscape_report_tracked(db, client.id)

        # EXPECTED BEHAVIOR: Events table must exist
        if not _table_exists(db, "report_job_events"):
            pytest.fail(
                f"COUNTEREXAMPLE: report_job_events table does not exist. "
                f"Generation for client '{brand_name}' completed with zero "
                f"lifecycle event infrastructure."
            )

        # Check events were created for this generation
        events_for_client = db.execute(
            text("""
                SELECT COUNT(e.id) FROM report_job_events e
                JOIN report_generation_jobs j ON e.job_id = j.id
                WHERE j.client_id = :cid
            """),
            {"cid": str(client.id)},
        ).scalar()

        assert events_for_client >= 2, (
            f"COUNTEREXAMPLE: generate_landscape_report_tracked() completed for client "
            f"'{brand_name}' but emitted {events_for_client} lifecycle events. "
            f"Expected ≥2 (REPORT_STARTED + REPORT_COMPLETED/FAILED)."
        )

    @given(brand_name=st_brand_name)
    @settings(
        max_examples=5,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_parallel_generations_should_deduplicate(
        self, db: Session, brand_name: str
    ):
        """When a job is already pending/processing for a client, calling
        generate_landscape_report_tracked() again SHOULD return the existing
        job (dedup) rather than creating a new one.

        Property: ∀ client_id with active job (pending/processing) →
                  get_or_create_report_job returns existing job, not new
                  AND DEDUP_BLOCKED event emitted
        """
        from app.services.onboarding.landscape_report import (
            generate_landscape_report_tracked,
            get_or_create_report_job,
        )
        from app.models.report_generation_job import ReportGenerationJob

        client = _create_test_client(db, brand_name, {"high": ["test"], "medium": [], "low": []}, None)

        # Create a job manually in "processing" state (simulates concurrent request)
        first_job = get_or_create_report_job(db, client.id, "portal", None)
        first_job.status = "processing"
        db.commit()
        first_job_id = first_job.id

        # Now call get_or_create_report_job 2 more times — should return same job
        second_job = get_or_create_report_job(db, client.id, "portal", None)
        third_job = get_or_create_report_job(db, client.id, "portal", None)

        # EXPECTED BEHAVIOR: Deduplication returns the same job
        assert second_job.id == first_job_id, (
            f"COUNTEREXAMPLE: get_or_create_report_job returned different job "
            f"(id={second_job.id}) instead of existing processing job (id={first_job_id}). "
            f"Deduplication not working."
        )
        assert third_job.id == first_job_id, (
            f"COUNTEREXAMPLE: get_or_create_report_job returned different job "
            f"(id={third_job.id}) instead of existing processing job (id={first_job_id}). "
            f"Deduplication not working."
        )

        # Only 1 job should exist for this client
        job_count = _count_rows(
            db, "report_generation_jobs",
            "client_id = :cid",
            {"cid": str(client.id)},
        )
        assert job_count == 1, (
            f"COUNTEREXAMPLE: Expected 1 job for client '{brand_name}' with dedup, "
            f"but found {job_count} jobs."
        )

        # DEDUP_BLOCKED events should have been emitted
        dedup_events = db.execute(
            text("""
                SELECT COUNT(*) FROM report_job_events
                WHERE job_id = :jid AND event_type = 'DEDUP_BLOCKED'
            """),
            {"jid": str(first_job_id)},
        ).scalar()
        assert dedup_events >= 2, (
            f"COUNTEREXAMPLE: Expected ≥2 DEDUP_BLOCKED events for concurrent calls, "
            f"got {dedup_events}."
        )

    @given(brand_name=st_brand_name)
    @settings(
        max_examples=5,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_failed_generation_should_record_error(
        self, db: Session, brand_name: str
    ):
        """When a step fails mid-generation, an error record SHOULD exist
        somewhere queryable with status='failed' and error_message populated.

        Property: ∀ client_id where generation fails →
                  ∃ job WHERE job.status = 'failed'
                  AND job.error_message IS NOT NULL
        """
        from app.services.onboarding.landscape_report import generate_landscape_report_tracked

        client = _create_test_client(db, brand_name, {"high": ["test"], "medium": [], "low": []}, None)

        # Simulate a failure during thread fetching by patching RedditThread query
        with patch(
            "app.services.onboarding.landscape_report.RedditThread",
            side_effect=Exception("Simulated DB failure"),
        ):
            # The tracked implementation catches errors and records them
            try:
                generate_landscape_report_tracked(db, client.id)
            except Exception:
                pass  # Function may or may not raise

        # EXPECTED BEHAVIOR: An error record should exist documenting this failure
        if not _table_exists(db, "report_generation_jobs"):
            pytest.fail(
                f"COUNTEREXAMPLE: No error tracking infrastructure exists. "
                f"Failed generation for client '{brand_name}' left zero queryable "
                f"error records. Failure is completely silent."
            )

        failed_jobs = _count_rows(
            db, "report_generation_jobs",
            "client_id = :cid AND status = 'failed'",
            {"cid": str(client.id)},
        )
        assert failed_jobs >= 1, (
            f"COUNTEREXAMPLE: Generation failed for client '{brand_name}' but "
            f"no job record with status='failed' exists. Error is completely "
            f"silent — no queryable evidence of the failure."
        )

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
        competitive_landscape=st_competitive_landscape,
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_completed_generation_should_have_full_job_record(
        self, db: Session, brand_name: str, keywords: dict,
        competitive_landscape: str | None
    ):
        """For all report generation requests where client_id is valid, a job
        entity SHOULD exist with status in (completed, failed), events >= 2,
        and report_data or error_message populated.

        This is the composite property assertion combining all observability
        requirements.

        Property: ∀ generation request with valid client_id →
                  ∃ job WHERE job.status ∈ ('completed', 'failed')
                  AND (job.report_data IS NOT NULL OR job.error_message IS NOT NULL)
                  AND COUNT(events for job) >= 2
        """
        from app.services.onboarding.landscape_report import generate_landscape_report_tracked

        client = _create_test_client(db, brand_name, keywords, competitive_landscape)

        # Call the tracked function under test
        result = generate_landscape_report_tracked(db, client.id)

        # EXPECTED BEHAVIOR: Full observability should exist after generation

        # Check 1: Job tracking table must exist
        if not _table_exists(db, "report_generation_jobs"):
            pytest.fail(
                f"COUNTEREXAMPLE: report_generation_jobs table does not exist. "
                f"Generation for '{brand_name}' completed successfully but has "
                f"zero observability. No job tracking, no status, no timestamps."
            )

        # Check 2: A job entity must exist with terminal status
        terminal_jobs = _count_rows(
            db, "report_generation_jobs",
            "client_id = :cid AND status IN ('completed', 'failed')",
            {"cid": str(client.id)},
        )
        assert terminal_jobs >= 1, (
            f"COUNTEREXAMPLE: Generation completed for '{brand_name}' but no job "
            f"with terminal status (completed/failed) exists. Status tracking broken."
        )

        # Check 3: Job must have report_data or error_message
        populated_jobs = db.execute(
            text("""
                SELECT COUNT(*) FROM report_generation_jobs
                WHERE client_id = :cid
                AND (report_data IS NOT NULL OR error_message IS NOT NULL)
            """),
            {"cid": str(client.id)},
        ).scalar()
        assert populated_jobs >= 1, (
            f"COUNTEREXAMPLE: Job exists for '{brand_name}' but neither "
            f"report_data nor error_message is populated. Result is lost."
        )

        # Check 4: Events table must exist with lifecycle records
        if not _table_exists(db, "report_job_events"):
            pytest.fail(
                f"COUNTEREXAMPLE: report_job_events table does not exist. "
                f"No lifecycle event audit trail for generation."
            )

        events_count = db.execute(
            text("""
                SELECT COUNT(e.id) FROM report_job_events e
                JOIN report_generation_jobs j ON e.job_id = j.id
                WHERE j.client_id = :cid
            """),
            {"cid": str(client.id)},
        ).scalar()
        assert events_count >= 2, (
            f"COUNTEREXAMPLE: Generation for '{brand_name}' has only "
            f"{events_count} lifecycle events. Expected ≥2 (START + END)."
        )


# ===========================================================================
# Property 2: Preservation — Report Content and Route Behavior Unchanged
# ===========================================================================


"""Preservation Property Tests — Report Content and Route Behavior Unchanged.

**Property 2: Preservation** — Report Content Unchanged

These tests MUST PASS on unfixed code — they encode the current correct
behavior that will be preserved after the fix.

GOAL: Verify that report generation logic (keyword matching, competitor detection,
thread query, report structure) works correctly and will continue to work after
the observability fix is applied.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
"""

from datetime import timedelta


# --- Additional Strategies for Preservation Tests ---

st_subreddit_name = st.sampled_from([
    "sysadmin", "devops", "networking", "cybersecurity", "cloudcomputing",
    "aws", "datascience", "machinelearning", "python", "homelab",
])

st_thread_title = st.sampled_from([
    "Best monitoring tools for enterprise?",
    "Looking for threat detection solutions",
    "How to automate compliance checks?",
    "Cloud security vs on-premise — thoughts?",
    "Our team needs better analytics",
    "What infrastructure do you recommend?",
    "Has anyone tried these platforms?",
    "Need advice on system management",
    "Tooling for DevOps workflow",
    "Open source vs commercial solutions?",
])

st_thread_body = st.sampled_from([
    "We're evaluating several options for our SOC team. Any recommendations?",
    "Looking to improve our detection capabilities. Budget is reasonable.",
    "Our current solution doesn't scale. Need something cloud-native.",
    "Just started a new role and need to set up monitoring from scratch.",
    "Comparing tools — what has worked well for your team?",
    "",
    None,
])


# --- Preservation Test Helpers ---

def _create_client_with_subreddits(
    db: Session, brand_name: str, keywords: dict | None,
    competitive_landscape: str | None, subreddit_names: list[str]
) -> Client:
    """Create a test client with subreddits assigned via ClientSubredditAssignment."""
    client = Client(
        client_name=f"PreservationClient_{uuid.uuid4().hex[:8]}",
        brand_name=brand_name,
        keywords=keywords,
        competitive_landscape=competitive_landscape,
        is_active=True,
    )
    db.add(client)
    db.flush()

    for sub_name in subreddit_names:
        # Create or find subreddit
        existing = db.query(Subreddit).filter(
            Subreddit.subreddit_name == sub_name
        ).first()
        if not existing:
            existing = Subreddit(subreddit_name=sub_name, is_active=True)
            db.add(existing)
            db.flush()

        # Create assignment
        assignment = ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=existing.id,
            is_active=True,
        )
        db.add(assignment)

    db.flush()
    return client


def _create_threads_for_subreddit(
    db: Session, subreddit_name: str, subreddit_id: uuid.UUID,
    count: int, ups_range: tuple[int, int] = (1, 50),
    brand_name: str | None = None, keywords: list[str] | None = None,
    competitor_names: list[str] | None = None,
) -> list:
    """Create RedditThread records for a subreddit within the 7-day window."""
    from app.models.thread import RedditThread

    threads = []
    now = datetime.now(timezone.utc)

    for i in range(count):
        title = f"Thread {i} in {subreddit_name}"
        body = f"Some discussion content about {subreddit_name} topic {i}."

        # Inject keywords into some threads
        if keywords and i % 3 == 0:
            kw = keywords[i % len(keywords)]
            body += f" Relevant to {kw} solutions."

        # Inject competitor mentions into some threads
        if competitor_names and i % 4 == 0:
            comp = competitor_names[i % len(competitor_names)]
            body += f" We evaluated {comp} for this."

        # Inject brand name into some threads
        if brand_name and i % 5 == 0:
            body += f" {brand_name} was mentioned by someone."

        thread = RedditThread(
            subreddit=subreddit_name,
            subreddit_id=subreddit_id,
            reddit_native_id=f"pres_{uuid.uuid4().hex[:10]}",
            post_title=title,
            post_body=body,
            ups=5 + (i * 3),  # varied engagement
            score=5 + (i * 3),
            created_at=now - timedelta(days=i % 6, hours=i % 12),
        )
        db.add(thread)
        threads.append(thread)

    db.flush()
    return threads


# --- Preservation Property Tests ---


class TestPreservationReportContent:
    """Property 2: Preservation — Report Content and Route Behavior Unchanged.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

    These tests MUST PASS on current (unfixed) code. They capture baseline
    behavior that the observability fix must not alter.
    """

    # Required keys that every successful report must contain
    REQUIRED_REPORT_KEYS = {
        "subreddits_monitored",
        "threads_found",
        "threads_relevant",
        "competitor_mentions",
        "high_intent_threads",
        "brand_absent_threads",
        "sample_drafts",
        "share_of_voice",
    }

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
        competitive_landscape=st_competitive_landscape,
    )
    @settings(
        max_examples=15,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_report_returns_all_required_keys_with_correct_types(
        self, db: Session, brand_name: str, keywords: dict,
        competitive_landscape: str | None,
    ):
        """For all valid client configurations, generate_landscape_report()
        returns a dict with all required keys and correct types.

        Property: ∀ valid client config →
                  report = generate_landscape_report(db, client_id)
                  AND report.keys ⊇ REQUIRED_KEYS
                  AND type(report["subreddits_monitored"]) == int
                  AND type(report["threads_found"]) == int
                  AND type(report["threads_relevant"]) == int
                  AND type(report["competitor_mentions"]) == list
                  AND type(report["high_intent_threads"]) == list
                  AND type(report["brand_absent_threads"]) == list
                  AND type(report["sample_drafts"]) == list
                  AND type(report["share_of_voice"]) == dict

        **Validates: Requirements 3.1**
        """
        from app.services.onboarding.landscape_report import generate_landscape_report

        client = _create_test_client(db, brand_name, keywords, competitive_landscape)

        report = generate_landscape_report(db, client.id)

        # Must not crash
        assert report is not None
        assert isinstance(report, dict)

        # If client not found, we get error dict — not expected for valid client
        assert "error" not in report, f"Unexpected error: {report.get('error')}"

        # All required keys present
        missing_keys = self.REQUIRED_REPORT_KEYS - set(report.keys())
        assert not missing_keys, (
            f"Report for '{brand_name}' missing keys: {missing_keys}. "
            f"Got keys: {set(report.keys())}"
        )

        # Type assertions for each key
        assert isinstance(report["subreddits_monitored"], int)
        assert isinstance(report["threads_found"], int)
        assert isinstance(report["threads_relevant"], int)
        assert isinstance(report["competitor_mentions"], list)
        assert isinstance(report["high_intent_threads"], list)
        assert isinstance(report["brand_absent_threads"], list)
        assert isinstance(report["sample_drafts"], list)
        assert isinstance(report["share_of_voice"], dict)

        # Share of voice structure check
        sov = report["share_of_voice"]
        assert "brand" in sov, "share_of_voice missing 'brand' key"
        assert "competitors" in sov, "share_of_voice missing 'competitors' key"
        assert isinstance(sov["brand"], int)
        assert isinstance(sov["competitors"], dict)

    @given(brand_name=st_brand_name)
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_client_with_no_subreddits_returns_graceful_empty_report(
        self, db: Session, brand_name: str,
    ):
        """Client with no subreddits configured returns empty/minimal report
        without crash.

        Property: ∀ client WHERE subreddits = [] →
                  report = generate_landscape_report(db, client_id)
                  AND report is not None
                  AND report["subreddits_monitored"] == 0
                  AND report["threads_found"] == 0

        **Validates: Requirements 3.2**
        """
        from app.services.onboarding.landscape_report import generate_landscape_report

        # Client with keywords but NO subreddits assigned
        client = _create_test_client(
            db, brand_name,
            {"high": ["security"], "medium": [], "low": []},
            None,
        )

        report = generate_landscape_report(db, client.id)

        # Must not crash
        assert report is not None
        assert isinstance(report, dict)
        assert "error" not in report

        # Should report zero subreddits and zero threads
        assert report["subreddits_monitored"] == 0
        assert report["threads_found"] == 0
        assert report["threads_relevant"] == 0
        assert report["competitor_mentions"] == []
        assert report["high_intent_threads"] == []
        assert report["brand_absent_threads"] == []

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_client_with_subreddits_but_no_threads_returns_graceful_report(
        self, db: Session, brand_name: str, keywords: dict,
    ):
        """Client with subreddits configured but no threads in 7-day window
        returns graceful empty report.

        Property: ∀ client WHERE subreddits > 0 AND threads_7d = 0 →
                  report = generate_landscape_report(db, client_id)
                  AND report["subreddits_monitored"] > 0
                  AND report["threads_found"] == 0

        **Validates: Requirements 3.2**
        """
        from app.services.onboarding.landscape_report import generate_landscape_report

        # Create client with subreddits but no threads in the subreddits
        sub_names = ["preservation_empty_sub_a", "preservation_empty_sub_b"]
        client = _create_client_with_subreddits(
            db, brand_name, keywords, None, sub_names,
        )

        report = generate_landscape_report(db, client.id)

        # Must not crash
        assert report is not None
        assert isinstance(report, dict)
        assert "error" not in report

        # Should report subreddits monitored but zero threads
        assert report["subreddits_monitored"] == len(sub_names)
        assert report["threads_found"] == 0
        assert report["threads_relevant"] == 0

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
        competitive_landscape=st.sampled_from([
            "CompetitorAlpha, CompetitorBeta, CompetitorGamma",
            "RivalCorp\nEnemyInc\nBigFish",
            "Alpha - market leader\nBeta - challenger",
        ]),
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_keyword_matching_and_competitor_detection_consistent(
        self, db: Session, brand_name: str, keywords: dict,
        competitive_landscape: str,
    ):
        """For given thread data, keyword matching and competitor detection
        produce consistent results across multiple invocations.

        Property: ∀ client config, ∀ thread data →
                  generate_landscape_report(db, client_id) called twice
                  produces identical report data

        **Validates: Requirements 3.1, 3.2**
        """
        from app.services.onboarding.landscape_report import generate_landscape_report

        # Create a sub to place threads in
        sub_name = f"pres_consist_{uuid.uuid4().hex[:6]}"
        client = _create_client_with_subreddits(
            db, brand_name, keywords, competitive_landscape, [sub_name],
        )

        # Find the subreddit entity to get its ID
        sub_entity = db.query(Subreddit).filter(
            Subreddit.subreddit_name == sub_name
        ).first()

        # Create threads with keywords and competitor mentions
        all_keywords = []
        for tier in ("high", "medium", "low"):
            all_keywords.extend(keywords.get(tier, []))

        from app.services.onboarding.landscape_report import _extract_competitor_names
        competitors = _extract_competitor_names(competitive_landscape)

        _create_threads_for_subreddit(
            db, sub_name, sub_entity.id, count=10,
            brand_name=brand_name,
            keywords=all_keywords,
            competitor_names=competitors,
        )

        # Generate report twice — results must be identical
        report1 = generate_landscape_report(db, client.id)
        report2 = generate_landscape_report(db, client.id)

        # Same thread data → same report (deterministic)
        assert report1["subreddits_monitored"] == report2["subreddits_monitored"]
        assert report1["threads_found"] == report2["threads_found"]
        assert report1["threads_relevant"] == report2["threads_relevant"]
        assert report1["share_of_voice"] == report2["share_of_voice"]
        assert len(report1["competitor_mentions"]) == len(report2["competitor_mentions"])
        assert len(report1["high_intent_threads"]) == len(report2["high_intent_threads"])
        assert len(report1["brand_absent_threads"]) == len(report2["brand_absent_threads"])

    @given(
        brand_name=st_brand_name,
        keywords=st_keyword_tier,
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_thread_query_7day_window_and_ordering(
        self, db: Session, brand_name: str, keywords: dict,
    ):
        """Thread query (7-day window, ordered by ups DESC, limit 200) produces
        same results regardless of tracking infrastructure.

        Property: ∀ client with subreddits and threads →
                  report["threads_found"] ≤ 200
                  AND threads are from 7-day window only
                  AND report["threads_found"] == actual fresh threads in DB

        **Validates: Requirements 3.1**
        """
        from app.services.onboarding.landscape_report import generate_landscape_report

        sub_name = f"pres_query_{uuid.uuid4().hex[:6]}"
        client = _create_client_with_subreddits(
            db, brand_name, keywords, None, [sub_name],
        )

        sub_entity = db.query(Subreddit).filter(
            Subreddit.subreddit_name == sub_name
        ).first()

        # Create 5 threads within 7-day window
        now = datetime.now(timezone.utc)
        from app.models.thread import RedditThread

        fresh_threads = []
        for i in range(5):
            t = RedditThread(
                subreddit=sub_name,
                subreddit_id=sub_entity.id,
                reddit_native_id=f"pres_q_{uuid.uuid4().hex[:10]}",
                post_title=f"Fresh thread {i}",
                post_body=f"Content about {keywords.get('high', ['test'])[0]}",
                ups=10 + i * 5,
                score=10 + i * 5,
                created_at=now - timedelta(days=i, hours=i),
            )
            db.add(t)
            fresh_threads.append(t)

        # Create 2 threads OLDER than 7 days (should NOT appear)
        for i in range(2):
            old_t = RedditThread(
                subreddit=sub_name,
                subreddit_id=sub_entity.id,
                reddit_native_id=f"pres_old_{uuid.uuid4().hex[:10]}",
                post_title=f"Old thread {i}",
                post_body="Old content",
                ups=100 + i,
                score=100 + i,
                created_at=now - timedelta(days=10 + i),
            )
            db.add(old_t)

        db.flush()

        report = generate_landscape_report(db, client.id)

        # Should find exactly the 5 fresh threads (not the 2 old ones)
        assert report["threads_found"] == 5, (
            f"Expected 5 fresh threads, got {report['threads_found']}. "
            f"7-day window filter may be broken."
        )
        # Must respect limit 200
        assert report["threads_found"] <= 200

    @given(brand_name=st_brand_name)
    @settings(
        max_examples=5,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_invalid_client_id_returns_error_without_crash(
        self, db: Session, brand_name: str,
    ):
        """For a non-existent client_id, generate_landscape_report returns
        an error dict without crashing.

        Property: ∀ client_id NOT IN clients →
                  report = generate_landscape_report(db, client_id)
                  AND report == {"error": "Client not found"}

        **Validates: Requirements 3.2**
        """
        from app.services.onboarding.landscape_report import generate_landscape_report

        fake_id = uuid.uuid4()
        report = generate_landscape_report(db, fake_id)

        assert report is not None
        assert isinstance(report, dict)
        assert report.get("error") == "Client not found"

    @given(
        competitive_landscape=st.sampled_from([
            "CompA, CompB, CompC",
            "RivalX\nRivalY\nRivalZ",
            "Alpha - market leader\nBeta - challenger\nGamma - newcomer",
            "One;Two;Three",
            "Single",
            "  LeadingSpaces  \n  TrailingSpaces  ",
        ]),
    )
    @settings(
        max_examples=10,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_competitor_extraction_deterministic(
        self, db: Session, competitive_landscape: str,
    ):
        """Competitor extraction from competitive_landscape text produces
        consistent results for same input.

        Property: ∀ competitive_landscape text →
                  _extract_competitor_names(text) called N times
                  returns same set of competitors each time

        **Validates: Requirements 3.1**
        """
        from app.services.onboarding.landscape_report import _extract_competitor_names

        result1 = _extract_competitor_names(competitive_landscape)
        result2 = _extract_competitor_names(competitive_landscape)

        # Same input → same output (deterministic)
        assert set(result1) == set(result2), (
            f"Non-deterministic competitor extraction: "
            f"run1={result1}, run2={result2}"
        )

        # Results are list of strings
        assert isinstance(result1, list)
        for comp in result1:
            assert isinstance(comp, str)
            assert len(comp) > 0
            assert len(comp) < 40  # enforced by the function

        # Max 10 competitors (enforced by the function)
        assert len(result1) <= 10

    @given(
        competitive_landscape=st.sampled_from([None, ""]),
    )
    @settings(
        max_examples=4,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_competitor_extraction_handles_empty_input(
        self, db: Session, competitive_landscape: str | None,
    ):
        """Competitor extraction handles None and empty string gracefully.

        Property: ∀ competitive_landscape ∈ {None, ""} →
                  _extract_competitor_names(text) returns []

        **Validates: Requirements 3.2**
        """
        from app.services.onboarding.landscape_report import _extract_competitor_names

        result = _extract_competitor_names(competitive_landscape)
        assert result == [], (
            f"Expected [] for empty input '{competitive_landscape}', got {result}"
        )
