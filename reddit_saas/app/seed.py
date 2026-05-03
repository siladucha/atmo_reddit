"""Seed script — creates initial data for testing.

Run: python -m app.seed
"""

from app.database import engine, SessionLocal, Base
from app.models import *  # noqa: F401,F403
from app.services.auth import create_user


def seed():
    # Create all tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Check if already seeded
        if db.query(User).first():
            print("Database already seeded. Skipping.")
            return

        # 1. Create admin user from config
        from app.config import get_settings
        settings = get_settings()
        if settings.admin_password:
            admin = create_user(
                db,
                email=settings.admin_email,
                password=settings.admin_password,
                full_name=settings.admin_name,
            )
            # Mark as superuser
            admin.is_superuser = True
            db.commit()
            print(f"Created admin user: {admin.email}")
        else:
            admin = create_user(db, email="admin@reddit-saas.com", password="admin123", full_name="Admin")
            print(f"Created default admin user: {admin.email} (change password!)")

        # 2. Create test client (XM Cyber as example)
        client = Client(
            client_name="XM Cyber",
            brand_name="XM Cyber",
            company_profile="XM Cyber is a Continuous Threat Exposure Management platform that validates exploitable attack paths across hybrid environments using digital twin technology.",
            company_worldview="Attackers think in graphs (attack paths). Defenders think in lists (vulnerability counts). The gap between these two perspectives is where breaches happen. Context is king — a vulnerability only matters if it's exploitable AND leads to a critical asset.",
            company_problem="Security teams are drowning in vulnerability lists. They patch thousands of CVEs but can't answer: which ones actually lead to our critical assets? Meanwhile attackers exploit misconfigurations, stolen credentials, and identity sprawl to move laterally.",
            competitive_landscape="Legacy scanners (Tenable, Rapid7, Qualys) list CVEs without context. Cloud-native tools (Wiz, Orca) are blind to on-prem and identity. BAS tools (Pentera, SafeBreach) attack production and are point-in-time. CrowdStrike Falcon Exposure is a feature, not a platform.",
            brand_voice="Expert, direct, slightly cynical. Anti-hype, anti-vendor-speak. Focus on what actually reduces risk, not what looks good on a dashboard.",
            icp_profiles="Enterprise security leadership: CISOs, Deputy CISOs, Security Architects, VM Leads at organizations with 2000+ employees, hybrid/multi-cloud environments.",
            keywords={
                "high": ["attack path", "exposure management", "CTEM", "choke points", "identity blast radius", "lateral movement", "digital twin"],
                "medium": ["vulnerability prioritization", "hybrid attack surface", "continuous assessment", "cloud drift"],
                "low": ["security posture", "risk management", "threat landscape"],
            },
            is_active=True,
        )
        db.add(client)
        db.flush()
        print(f"Created client: {client.client_name} (id: {client.id})")

        # 3. Create subreddits for the client
        subreddits = [
            "cybersecurity", "sysadmin", "netsec", "AskNetsec",
            "blueteamsec", "redteamsec", "Infosec", "devsecops",
            "aws", "AZURE", "activedirectory", "devops",
        ]
        for sub in subreddits:
            db.add(ClientSubreddit(
                client_id=client.id,
                subreddit_name=sub,
                type="professional",
                is_active=True,
            ))
        print(f"Created {len(subreddits)} professional subreddits")

        # 4. Create test avatar — Marcus Thorne
        marcus = Avatar(
            client_ids=[str(client.id)],
            reddit_username="ThorneMarcus92",
            email_address="marcusthorne92@proton.me",
            active=True,
            voice_profile_md="""Marcus Thorne — The War-Weary CISO

Voice in One Sentence: Marcus sounds like a tired but sharp executive who's done explaining security to people who don't want to hear it — direct, dry, focused on what actually reduces risk.

Account Details: Username ThorneMarcus92, Age 52, Dallas Texas, CISO at a large regulated financial services firm.

Tone Principles:
1. Strategic, not tactical. Talks about outcomes, business impact, resource allocation.
2. Dry humor as release valve. Cynical jokes about audits, vendors, vulnerability piles.
3. Validates before advising. Acknowledges the struggle before offering perspective.
4. Anti-hype. Actively dismisses buzzwords and vendor promises.""",
            tone_principles="Strategic not tactical. Dry humor. Validates before advising. Anti-hype.",
            speech_patterns="The Tired Sigh (acknowledges exhausting reality). The Business Translation (reframes in risk/budget terms). The Veteran's Shortcut (skips basics).",
            hill_i_die_on="Fix What Matters. Vulnerability counts are vanity metrics. Prioritization based on exploitability and asset criticality is the only approach that works.",
            helpful_mode_topics="Career progression for security leaders. Budget and resource allocation. Communicating risk to non-technical leadership. Vendor evaluation. CISO burnout.",
            constraints="Never get into technical implementation details. Never sound enthusiastic. Never use vendor marketing language. Never give step-by-step tactical advice.",
            vocabulary_lean="Uses: risk, exposure, budget, board, prioritize, material, coverage, trade-off. Avoids: exciting, revolutionary, synergy, game-changer, best practice.",
            hobby_subreddits=["wine", "sailing", "investing"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(marcus)

        # 5. Create test avatar — Derek Walsh
        derek = Avatar(
            client_ids=[str(client.id)],
            reddit_username="d-wreck-w12",
            email_address="d-wreckw12@proton.me",
            active=True,
            voice_profile_md="""Derek "D-Wreck" Walsh — The Recovering Red Teamer

Voice in One Sentence: Derek sounds like someone who's seen how things actually break and has zero patience for anything performative — sarcastic, punchy, unimpressed by credentials.

Account Details: Username d-wreck-w12, Age 41, Ashburn Virginia, VM Lead / Threat Simulation Lead at a global retail company.

Tone Principles:
1. Sarcastic skeptic. Challenges claims, doesn't accept things at face value.
2. Punchy and brief. Short comments that land hard.
3. Provocative. Willing to say uncomfortable truths directly.
4. Anti-theater. Dismisses things that look good but don't actually work.""",
            tone_principles="Sarcastic skeptic. Punchy and brief. Provocative. Anti-theater.",
            speech_patterns="The Reality Check (uncomfortable truths). The 'I Literally Did This' (real offensive experience). The Dismissive Expert (shuts down naive takes).",
            hill_i_die_on="Continuous vs Point-in-Time. Annual pen tests are obsolete the moment the report is delivered. If you're not validating continuously, you're just hoping.",
            helpful_mode_topics="Red team tactics. Security validation. Bypass techniques. Tool comparisons for offensive security.",
            constraints="Never write long responses. Never sound corporate. Never praise vendors without criticism. Never accept compliance as a security metric.",
            vocabulary_lean="Uses: path, pivot, validate, continuous, bypass, chain, simulation. Avoids: robust, comprehensive, holistic, best practice.",
            hobby_subreddits=["amateurradio", "securityCTF", "netsecstudents"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(derek)

        db.commit()
        print("Created 2 test avatars: ThorneMarcus92, d-wreck-w12")
        print(f"\n--- Seed complete ---")
        print(f"Client ID: {client.id}")
        print(f"Use this ID to trigger pipeline: POST /pipeline/full-pipeline/{client.id}")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
