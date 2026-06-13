"""Demo Seed — Creates a pre-built Discovery session with realistic data.

Purpose: Tzvi can demo the full Discovery flow on Zoom without waiting for
Reddit API calls. The session has:
- A realistic client brief (anonymized XM Cyber / attack surface management)
- 8 extracted entities (products, audiences, problems, competitors)
- 5 confirmed hypotheses with real-looking Reddit signals
- A complete Visibility Report
- All costs logged at $0 (demo data)

Usage:
    from app.services.discovery.demo_seed import create_demo_session
    session = create_demo_session(db, operator_user_id)
    # Session is immediately complete with report ready for export
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.logging_config import get_logger
from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.models.visibility_report import VisibilityReport

logger = get_logger(__name__)

# --- Demo Data ---

DEMO_BRIEF = """CyberShield is an attack surface management platform for mid-market enterprises (500-5000 employees). 
We help security teams discover, monitor, and reduce their external attack surface — including shadow IT, 
exposed APIs, misconfigured cloud assets, and forgotten subdomains. Our ICP is CISO / Head of Security 
at Series B-D SaaS companies who are scaling fast and losing visibility into their expanding infrastructure.

Key differentiators: agentless discovery (no deployment needed), integration with existing SIEM/SOAR tools, 
and automated remediation playbooks. Competitors include Censys, Shodan, CyCognito, and Randori (IBM).

We're evaluating Reddit as a channel to build organic authority in cybersecurity communities through 
expert-level participation in discussions about attack surface management, vulnerability disclosure, 
and infrastructure security."""

DEMO_ENTITIES = [
    {"name": "Attack Surface Management", "category": "product"},
    {"name": "External Attack Surface Discovery", "category": "product"},
    {"name": "CISO / Security Leader", "category": "audience"},
    {"name": "DevSecOps Engineer", "category": "audience"},
    {"name": "Shadow IT Visibility", "category": "problem"},
    {"name": "Cloud Misconfiguration Detection", "category": "problem"},
    {"name": "Censys", "category": "competitor"},
    {"name": "CyCognito", "category": "competitor"},
    {"name": "Cybersecurity SaaS", "category": "industry"},
    {"name": "Vulnerability Management", "category": "use_case"},
]

DEMO_HYPOTHESES = [
    {
        "statement": "r/cybersecurity has active discussions about attack surface management with 50+ posts/month and average engagement of 15+ upvotes",
        "category": "market_research",
        "confidence_score": 82,
        "status": "confirmed",
        "reddit_signals": {
            "subreddits": [
                {"name": "r/cybersecurity", "subscribers": 870000, "posts_30d": 2400, "avg_engagement": 23, "relevance_score": 85},
            ],
            "total_posts_found": 67,
            "avg_engagement_overall": 18,
        },
        "provenance": {
            "triggering_entities": [{"name": "Attack Surface Management", "category": "product"}],
            "reasoning": "Direct product category match with subreddit's core topic area",
            "search_terms": ["attack surface management", "ASM", "external attack surface"],
        },
    },
    {
        "statement": "r/netsec is a high-value community where CISOs and senior security professionals discuss vulnerability management and ASM tools (technical depth, decision-maker audience)",
        "category": "clients",
        "confidence_score": 78,
        "status": "confirmed",
        "reddit_signals": {
            "subreddits": [
                {"name": "r/netsec", "subscribers": 520000, "posts_30d": 890, "avg_engagement": 32, "relevance_score": 79},
            ],
            "total_posts_found": 34,
            "avg_engagement_overall": 28,
        },
        "provenance": {
            "triggering_entities": [{"name": "CISO / Security Leader", "category": "audience"}, {"name": "Vulnerability Management", "category": "use_case"}],
            "reasoning": "Decision-maker audience overlap with technical content requirements",
            "search_terms": ["vulnerability management tools", "attack surface", "CISO recommendation"],
        },
    },
    {
        "statement": "r/blueteam actively discusses defensive security tooling including ASM, EDR, and SIEM with a practitioner audience that evaluates new tools",
        "category": "feedback",
        "confidence_score": 71,
        "status": "confirmed",
        "reddit_signals": {
            "subreddits": [
                {"name": "r/blueteam", "subscribers": 48000, "posts_30d": 320, "avg_engagement": 12, "relevance_score": 72},
            ],
            "total_posts_found": 22,
            "avg_engagement_overall": 14,
        },
        "provenance": {
            "triggering_entities": [{"name": "DevSecOps Engineer", "category": "audience"}],
            "reasoning": "Practitioner community actively discussing tool evaluations",
            "search_terms": ["attack surface tool", "ASM tool comparison", "blue team tools"],
        },
    },
    {
        "statement": "r/sysadmin has strong engagement around shadow IT and cloud misconfiguration topics, with IT leaders asking for solutions in this space",
        "category": "clients",
        "confidence_score": 65,
        "status": "confirmed",
        "reddit_signals": {
            "subreddits": [
                {"name": "r/sysadmin", "subscribers": 920000, "posts_30d": 4200, "avg_engagement": 19, "relevance_score": 58},
            ],
            "total_posts_found": 45,
            "avg_engagement_overall": 16,
        },
        "provenance": {
            "triggering_entities": [{"name": "Shadow IT Visibility", "category": "problem"}, {"name": "Cloud Misconfiguration Detection", "category": "problem"}],
            "reasoning": "Large audience discussing exact problems the product solves",
            "search_terms": ["shadow IT discovery", "cloud misconfiguration", "unknown assets"],
        },
    },
    {
        "statement": "r/devsecops discusses infrastructure security scanning and shift-left security approaches where ASM integrations are relevant",
        "category": "partners",
        "confidence_score": 61,
        "status": "confirmed",
        "reddit_signals": {
            "subreddits": [
                {"name": "r/devsecops", "subscribers": 35000, "posts_30d": 180, "avg_engagement": 8, "relevance_score": 63},
            ],
            "total_posts_found": 15,
            "avg_engagement_overall": 9,
        },
        "provenance": {
            "triggering_entities": [{"name": "DevSecOps Engineer", "category": "audience"}, {"name": "External Attack Surface Discovery", "category": "product"}],
            "reasoning": "Pipeline integration audience interested in automated scanning",
            "search_terms": ["devsecops scanning", "shift left security", "infrastructure security"],
        },
    },
    {
        "statement": "r/msp frequently discusses cybersecurity tool recommendations for managed service providers, representing a channel partner opportunity",
        "category": "partners",
        "confidence_score": 42,
        "status": "rejected",
        "rejection_reason": "Low relevance: MSPs discuss basic tools, not enterprise ASM. Wrong ICP.",
        "reddit_signals": {
            "subreddits": [
                {"name": "r/msp", "subscribers": 120000, "posts_30d": 1800, "avg_engagement": 11, "relevance_score": 28},
            ],
            "total_posts_found": 8,
            "avg_engagement_overall": 6,
        },
        "provenance": {
            "triggering_entities": [{"name": "Cybersecurity SaaS", "category": "industry"}],
            "reasoning": "Channel partner hypothesis - MSPs as resellers",
            "search_terms": ["MSP security tools", "managed security", "ASM for MSPs"],
        },
    },
]

DEMO_REPORT_CONTENT = {
    "executive_summary": (
        "Reddit presents a strong organic opportunity for CyberShield in the attack surface management space. "
        "Five key communities demonstrate active discussions about ASM, vulnerability management, and infrastructure "
        "security — with a combined reach of 2.4M+ subscribers and 8,000+ posts/month. The competitive landscape "
        "shows Censys and CyCognito have minimal Reddit presence, creating a first-mover advantage opportunity. "
        "Recommended strategy: build authority through expert participation in r/cybersecurity and r/netsec first, "
        "then expand to r/blueteam and r/sysadmin for broader practitioner reach."
    ),
    "demand_assessment": (
        "Attack surface management discussions appear in 4 of the 5 confirmed communities, averaging "
        "15-32 upvotes per relevant post. The audience skews technical (engineers, architects, team leads) "
        "with periodic CISO-level threads asking for tool recommendations. Monthly volume of directly "
        "relevant discussions: ~180 posts across confirmed communities. Seasonal pattern: spikes after "
        "major breach disclosures (e.g., MOVEit, Okta) with 2-3x normal engagement."
    ),
    "communities": [
        {"name": "r/cybersecurity", "subscribers": 870000, "daily_posts": 80, "relevance": 85, "approach": "Expert commentary on ASM-related news, helpful responses to tool questions"},
        {"name": "r/netsec", "subscribers": 520000, "daily_posts": 30, "relevance": 79, "approach": "Technical deep-dives, vulnerability analysis, research sharing"},
        {"name": "r/sysadmin", "subscribers": 920000, "daily_posts": 140, "relevance": 58, "approach": "Practical solutions to shadow IT and cloud visibility problems"},
        {"name": "r/blueteam", "subscribers": 48000, "daily_posts": 11, "relevance": 72, "approach": "Tool comparisons, defensive playbook discussions"},
        {"name": "r/devsecops", "subscribers": 35000, "daily_posts": 6, "relevance": 63, "approach": "CI/CD security integration, shift-left scanning discussions"},
    ],
    "discussion_activity": (
        "Across confirmed communities, we identified 183 relevant posts in the last 30 days. "
        "Peak engagement hours: 14:00-18:00 UTC (US business hours). Thread depth averages 12-20 "
        "comments for ASM-related topics, indicating genuine community interest and discussion potential."
    ),
    "entry_points": [
        "Weekly 'What tools are you using?' threads in r/cybersecurity (high engagement, tool recommendations)",
        "Post-breach discussion threads (natural context for mentioning ASM capabilities)",
        "Cloud security misconfiguration stories in r/sysadmin (problem-solution opportunities)",
        "Comparison threads: 'Censys vs X vs Y' in r/netsec (direct product positioning)",
        "Tool evaluation threads in r/blueteam (detailed technical credibility building)",
    ],
    "competitive_landscape": (
        "Competitor Reddit presence is surprisingly weak:\n"
        "- Censys: 2-3 mentions/month, mostly user questions (no official presence)\n"
        "- CyCognito: Near-zero Reddit presence\n"
        "- Randori (IBM): Occasional mentions in acquisition-related threads only\n"
        "- Shodan: Strong brand recognition but positioned as research tool, not enterprise ASM\n\n"
        "This creates a significant first-mover advantage. By establishing expert authority before "
        "competitors invest in Reddit, CyberShield can own the 'attack surface management' conversation."
    ),
    "visibility_outcomes": [
        {"type": "brand_authority", "probability": "high", "reasoning": "Consistent expert participation in r/cybersecurity and r/netsec builds recognizable authority within 3-6 months"},
        {"type": "lead_generation", "probability": "medium", "reasoning": "Direct DMs from engaged users asking about tools; expect 2-5 warm leads/month after authority established"},
        {"type": "competitive_displacement", "probability": "high", "reasoning": "No competitors actively building Reddit presence; first-mover advantage in organic search"},
        {"type": "content_amplification", "probability": "medium", "reasoning": "High-karma posts get indexed by Google and cited by AI assistants as reference material"},
        {"type": "hiring_signal", "probability": "low", "reasoning": "Potential talent pipeline from engaged community members, but not primary use case"},
    ],
    "risks_and_limitations": (
        "1. Authenticity detection: Reddit communities are hostile to obvious marketing. All engagement "
        "must be genuinely helpful, not promotional.\n"
        "2. Time to value: Minimum 8-12 weeks before meaningful authority is established. First 4 weeks "
        "are credibility building (zero brand mentions).\n"
        "3. Moderation risk: r/netsec has strict no-self-promotion rules. Any perceived shilling results "
        "in immediate ban.\n"
        "4. Measurement lag: Reddit karma and engagement metrics are available in real-time, but "
        "lead attribution to specific posts is difficult to track.\n"
        "5. Platform risk: Reddit ToS prohibits coordinated inauthentic behavior. Strategy must rely "
        "on genuinely expert content that adds value to discussions."
    ),
}


def create_demo_session(
    db: DBSession,
    operator_user_id: uuid.UUID,
) -> DiscoverySession:
    """Create a complete demo Discovery session with pre-built data.

    The session is created in 'completed' state with all entities, hypotheses,
    and report pre-populated. No Reddit API calls needed.

    Args:
        db: Database session.
        operator_user_id: User ID of the operator creating the demo.

    Returns:
        Completed DiscoverySession with report ready for export.
    """
    now = datetime.now(timezone.utc)

    # Create session
    session = DiscoverySession(
        operator_user_id=operator_user_id,
        client_brief=DEMO_BRIEF.strip(),
        prospect_name="CyberShield (Demo)",
        client_id=None,
        status="completed",
        current_iteration=2,
        completed_at=now,
        session_metadata={
            "demo": True,
            "research_progress": {"total": 6, "completed": 6, "in_progress": 0},
        },
        total_ai_cost_usd=0.0042,  # Realistic cost for entity+hypothesis+report
    )
    db.add(session)
    db.flush()

    # Create entities
    for ent in DEMO_ENTITIES:
        entity = DiscoveryEntity(
            session_id=session.id,
            name=ent["name"],
            category=ent["category"],
            source="llm",
        )
        db.add(entity)

    # Create hypotheses
    for hyp_data in DEMO_HYPOTHESES:
        hyp = DiscoveryHypothesis(
            session_id=session.id,
            iteration_number=1,
            statement=hyp_data["statement"],
            category=hyp_data["category"],
            confidence_score=hyp_data["confidence_score"],
            confidence_delta=hyp_data["confidence_score"] - 50,
            status=hyp_data["status"],
            reddit_signals=hyp_data["reddit_signals"],
            provenance=hyp_data["provenance"],
            rejection_reason=hyp_data.get("rejection_reason"),
            decided_at=now - timedelta(minutes=5),
        )
        db.add(hyp)

    # Create visibility report
    report = VisibilityReport(
        session_id=session.id,
        content=DEMO_REPORT_CONTENT,
        report_version=1,
        model_used="gemini/gemini-2.5-flash-lite (demo)",
        generation_cost_usd=0.0018,
    )
    db.add(report)

    db.commit()
    db.refresh(session)

    logger.info(f"Demo Discovery session created: {session.id}")
    return session
