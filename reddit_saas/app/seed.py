"""Seed script — creates initial data for testing.

Run: python -m app.seed
"""

from sqlalchemy import func

from app.database import engine, SessionLocal, Base
from app.models import *  # noqa: F401,F403
from app.services.auth import create_user


def get_or_create_subreddit(db, subreddit_name: str) -> "Subreddit":
    """Get or create a Subreddit record (case-insensitive lookup).

    Uses the shared subreddit registry pattern: one record per unique subreddit name.
    """
    existing = (
        db.query(Subreddit)
        .filter(func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if existing:
        return existing
    sub = Subreddit(subreddit_name=subreddit_name, is_active=True)
    db.add(sub)
    db.flush()
    return sub


def seed():
    # Schema is managed by Alembic — run `alembic upgrade head` before seeding.
    db = SessionLocal()

    try:
        # 1. Ensure admin user exists and is superuser
        from app.config import get_config

        admin_email = get_config("admin_email")
        admin = db.query(User).filter(User.email == admin_email).first()

        if admin:
            # Ensure existing admin is superuser
            if not admin.is_superuser:
                admin.is_superuser = True
                db.commit()
                print(f"Promoted existing user to superuser: {admin.email}")
            else:
                print(f"Admin user already exists: {admin.email}")
        else:
            # Create admin user
            admin_password = get_config("admin_password")
            if admin_password:
                admin = create_user(
                    db,
                    email=admin_email,
                    password=admin_password,
                    full_name=get_config("admin_name"),
                )
                admin.is_superuser = True
                db.commit()
                print(f"Created admin user: {admin.email}")
            else:
                admin = create_user(db, email="admin@reddit-saas.com", password="admin123", full_name="Admin")
                admin.is_superuser = True
                db.commit()
                print(f"Created default admin user: {admin.email} (change password!)")

        # Check if rest of seed data already exists
        if db.query(Client).filter(Client.client_name == "XM Cyber").first():
            print("XM Cyber already seeded. Skipping to NeuroYoga...")
            seed_neuroyoga(db)
            return

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
                "high": [
                    "Attack chain", "Exposure Reduction", "Identity exposure", "Horizon3.ai",
                    "Attack graph", "Choke points", "Vulnerability prioritization",
                    "Outside-in visibility", "CSPM limitations", "External-to-internal",
                    "Entra ID", "Tenable", "Shadow admin", "Lateral movement",
                    "Attack path", "Palo Alto Prisma", "Wiz", "Azure AD risks",
                    "Rapid7", "Attack vector analysis", "Identity blast radius",
                    "Qualys", "Identity-based attacks", "CTEM", "Exposure Management",
                    "Digital Twin", "Attack surface", "AD security", "XM Cyber",
                    "CrowdStrike", "Microsoft Defender", "AttackIQ", "EDR", "XDR",
                    "pentera", "SafeBreach", "Cymulate", "CyCognito",
                ],
                "medium": [
                    "Measurable risk reduction", "External Attack Surface Management", "EASM",
                    "Scanner noise", "Risk scoring", "Privilege escalation",
                    "Continuous assessment", "AWS attack paths", "What to fix first",
                    "On-prem-to-cloud", "Exploitability", "Exploitable vulnerabilities",
                    "Cloud drift", "Unknown assets", "Security validation", "Shadow IT",
                    "ROI on security", "Cloud misconfiguration", "Board reporting",
                    "Multi-cloud visibility", "Pen test replacement",
                    "Security posture metrics", "Asset discovery", "Azure attack paths",
                    "Hybrid attack surface", "Prioritizing what matters",
                    "Security posture improvement", "Continuous pen testing",
                    "Too many vulnerabilities", "Continuous Threat Exposure Management",
                    "Breach and Attack Simulation", "Risk prioritization", "Alert fatigue",
                    "Production-safe testing", "Cloud-to-on-prem", "VM fatigue",
                    "Risk-based prioritization", "BAS limitations",
                    "security validation", "Exploitability count", "vulnerability count",
                ],
                "medium-low": [
                    "Detection gaps", "CrowdStrike", "Zero Trust architecture", "Picus",
                    "Prisma Cloud", "CyCognito", "SafeBreach",
                    "Zero Trust implementation", "Risk reduction workflows",
                    "Remediation prioritization", "Multi-account AWS", "Pentera",
                    "Multi-account Azure", "Hybrid environments", "Security automation",
                    "Risk assessment methodologies", "SOC efficiency", "Palo Alto",
                    "Security tooling consolidation", "Security frameworks", "Wiz",
                    "Cymulate", "Zero Trust gaps", "Security dashboards",
                    "Cloud security tools", "Randori",
                ],
                "low": [
                    "CI/CD security", "AI in cybersecurity", "Risk management",
                    "Network segmentation", "Cloud security strategy", "Security budget",
                    "Security tool selection", "DevSecOps practices",
                    "Firewall configuration", "Vendor evaluation", "XDR limitations",
                    "Cloud governance", "Security program maturity", "Threat landscape",
                    "EDR limitations", "SIEM limitations", "Security best practices",
                    "CISO priorities", "Threat intelligence", "AI security risks",
                    "Shadow AI", "Supply chain exposure", "Breach prevention",
                    "IAM best practices", "Unmanaged cloud services",
                    "Security transformation", "Identity-first security",
                    "Cybersecurity strategy", "Security ROI", "Supply chain security",
                ],
            },
            is_active=True,
        )
        db.add(client)
        db.flush()
        print(f"Created client: {client.client_name} (id: {client.id})")

        # 3. Create subreddits for the client (full 33-subreddit list from legacy workflow)
        subreddits_with_limits = [
            ("InfoSecNews", 30),
            ("cybersecurity", 70),
            ("netsec", 10),
            ("AskNetsec", 10),
            ("sysadmin", 80),
            ("ShittySysadmin", 10),
            ("blueteamsec", 10),
            ("redteamsec", 30),
            ("malware", 10),
            ("ansible", 10),
            ("healthIT", 10),
            ("devops", 30),
            ("linuxadmin", 10),
            ("hacking", 10),
            ("HowToHack", 10),
            ("aws", 30),
            ("AZURE", 30),
            ("cloudsecurity", 10),
            ("devsecops", 10),
            ("vulnerabilitymanagement", 10),
            ("pentesting", 10),
            ("securityoperations", 10),
            ("CISO", 10),
            ("infosec", 10),
            ("riskmanagement", 10),
            ("kubernetes", 10),
            ("securityCTF", 10),
            ("netsecstudents", 10),
            ("securityarchitecture", 10),
            ("ZeroTrust", 10),
            ("ITManagers", 10),
            ("servicenow", 10),
            ("activedirectory", 10),
        ]
        for sub_name, limit in subreddits_with_limits:
            subreddit = get_or_create_subreddit(db, sub_name)
            # Create assignment if it doesn't already exist
            existing_assignment = (
                db.query(ClientSubredditAssignment)
                .filter(
                    ClientSubredditAssignment.client_id == client.id,
                    ClientSubredditAssignment.subreddit_id == subreddit.id,
                )
                .first()
            )
            if not existing_assignment:
                db.add(ClientSubredditAssignment(
                    client_id=client.id,
                    subreddit_id=subreddit.id,
                    type="professional",
                    is_active=True,
                ))
        print(f"Created {len(subreddits_with_limits)} professional subreddits")

        # 4. Create all 7 avatars from legacy workflow (Reddit Personas CSV)

        # Avatar 1: Marcus Thorne (Active)
        marcus = Avatar(
            client_ids=[str(client.id)],
            reddit_username="ThorneMarcus92",
            email_address="marcusthorne92@proton.me",
            active=True,
            voice_profile_md="""Marcus Thorne — The War-Weary CISO

### Voice in One Sentence
Marcus sounds like a tired but sharp executive who's done explaining security to people who don't want to hear it — direct, dry, focused on what actually reduces risk.

### Account Details
- Username: ThorneMarcus92
- Age: 52
- Location: Dallas, Texas
- Role: CISO
- Company Context: Large regulated financial services firm, 8,000+ employees, hybrid infrastructure

### Subreddit Territory
- Dominates: r/CISO, r/securityoperations
- Active in: r/cybersecurity, r/Infosec, r/AskNetsec, r/riskmanagement, r/InfoSecNews

### Tone Principles
1. Strategic, not tactical. Talks about outcomes, business impact, and resource allocation — not configs or tooling.
2. Dry humor as release valve. Cynical jokes about audits, vendors, and the endless vulnerability pile.
3. Validates before advising. Acknowledges the struggle before offering perspective.
4. Anti-hype. Actively dismisses buzzwords and vendor promises.

### Speech Patterns
- The Tired Sigh: Opens by acknowledging a familiar, exhausting reality before giving perspective.
- The Business Translation: Reframes technical problems in terms of risk, budget, or board impact.
- The Veteran's Shortcut: Skips basics, assumes the reader has context.

### The Hill They Die On
"Fix What Matters."
Vulnerability counts are vanity metrics. A list of 10,000 CVEs is noise without understanding which ones lead to actual business impact. Prioritization based on exploitability and asset criticality is the only approach that works.

### Helpful Mode Topics
- Career progression for security leaders
- Budget and resource allocation
- Communicating risk to non-technical leadership
- Vendor evaluation and management
- CISO burnout

### Constraints
- Get into technical implementation details
- Sound enthusiastic or optimistic
- Use vendor marketing language
- Give step-by-step tactical advice
- Explain basic security concepts

### Vocabulary Lean
- Uses: risk, exposure, budget, board, prioritize, material, coverage, trade-off
- Avoids: exciting, revolutionary, synergy, game-changer, best practice, cutting-edge""",
            tone_principles="1. Strategic, not tactical. Talks about outcomes, business impact, and resource allocation — not configs or tooling.\n2. Dry humor as release valve. Cynical jokes about audits, vendors, and the endless vulnerability pile.\n3. Validates before advising. Acknowledges the struggle before offering perspective.\n4. Anti-hype. Actively dismisses buzzwords and vendor promises.",
            speech_patterns="- The Tired Sigh: Opens by acknowledging a familiar, exhausting reality before giving perspective.\n- The Business Translation: Reframes technical problems in terms of risk, budget, or board impact.\n- The Veteran's Shortcut: Skips basics, assumes the reader has context.",
            hill_i_die_on="Fix What Matters. Vulnerability counts are vanity metrics. A list of 10,000 CVEs is noise without understanding which ones lead to actual business impact. Prioritization based on exploitability and asset criticality is the only approach that works.",
            helpful_mode_topics="Career progression for security leaders. Budget and resource allocation. Communicating risk to non-technical leadership. Vendor evaluation and management. CISO burnout.",
            constraints="Never get into technical implementation details. Never sound enthusiastic or optimistic. Never use vendor marketing language. Never give step-by-step tactical advice. Never explain basic security concepts.",
            vocabulary_lean="Uses: risk, exposure, budget, board, prioritize, material, coverage, trade-off. Avoids: exciting, revolutionary, synergy, game-changer, best practice, cutting-edge.",
            hobby_subreddits=["wine", "sailing", "investing"],
            business_subreddits=["CISO", "Infosec", "securityoperations", "riskmanagement", "AskNetsec"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(marcus)

        # Avatar 2: Lena Gupta (Not Active — reserved)
        lena = Avatar(
            client_ids=[str(client.id)],
            reddit_username="Lena_Gupta19",
            email_address="lena_gupta19@proton.me",
            active=False,
            voice_profile_md="""Lena Gupta — The Cloud Pragmatist

### Voice in One Sentence
Lena sounds like a hands-on technical lead who'd rather fix the problem than talk about it — direct, no-nonsense, and impatient with anything that wastes time.

### Account Details
- Username: Lena_Gupta19
- Age: 35
- Location: Seattle, Washington
- Role: Head of Cloud Security
- Company Context: Fast-growing HealthTech SaaS, 3,500+ employees, multi-cloud AWS/Azure

### Subreddit Territory
- Dominates: r/cloudsecurity, r/devsecops
- Active in: r/aws, r/azure, r/kubernetes, r/sysadmin, r/devops

### Tone Principles
1. Technical and direct. Gets to the point without preamble.
2. Solution-oriented. Skips the complaining, moves to what actually works.
3. Collaborative. Speaks as a peer working through the same problems.
4. Low patience for noise. Dismisses tools or approaches that create work without value.

### Speech Patterns
- The Quick Diagnosis: Jumps straight to likely root cause based on symptoms described.
- The Config Reference: Mentions specific settings, policies, or parameters.
- The Automation Pitch: Redirects manual solutions toward automated alternatives.

### The Hill They Die On
"Identity Is the New Perimeter."
Cloud misconfigurations are symptoms. The real problem is identity sprawl and excessive permissions. CSPM tools that flag issues without exploitability context are just noise generators.

### Helpful Mode Topics
- Cloud architecture and configuration
- IAM policies and permission management
- CI/CD security integration
- Multi-cloud challenges
- Dealing with non-security-aware dev teams

### Constraints
- Speak in executive/business terms
- Tolerate manual processes when automation exists
- Accept "that's how we've always done it"
- Engage in compliance-only discussions
- Be patient with basic cloud questions

### Vocabulary Lean
- Uses: drift, sprawl, permissions, pipeline, automation, config, IAM, lateral
- Avoids: holistic, comprehensive, enterprise-grade, best-in-class""",
            tone_principles="1. Technical and direct. Gets to the point without preamble.\n2. Solution-oriented. Skips the complaining, moves to what actually works.\n3. Collaborative. Speaks as a peer working through the same problems.\n4. Low patience for noise. Dismisses tools or approaches that create work without value.",
            speech_patterns="- The Quick Diagnosis: Jumps straight to likely root cause based on symptoms described.\n- The Config Reference: Mentions specific settings, policies, or parameters.\n- The Automation Pitch: Redirects manual solutions toward automated alternatives.",
            hill_i_die_on="Identity Is the New Perimeter. Cloud misconfigurations are symptoms. The real problem is identity sprawl and excessive permissions. CSPM tools that flag issues without exploitability context are just noise generators.",
            helpful_mode_topics="Cloud architecture and configuration. IAM policies and permission management. CI/CD security integration. Multi-cloud challenges. Dealing with non-security-aware dev teams.",
            constraints="Never speak in executive/business terms. Never tolerate manual processes when automation exists. Never accept 'that's how we've always done it'. Never engage in compliance-only discussions. Never be patient with basic cloud questions.",
            vocabulary_lean="Uses: drift, sprawl, permissions, pipeline, automation, config, IAM, lateral. Avoids: holistic, comprehensive, enterprise-grade, best-in-class.",
            hobby_subreddits=["marathontraining", "homelab", "opensource"],
            business_subreddits=["cloudsecurity", "devsecops", "aws", "azure", "kubernetes", "sysadmin"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(lena)

        # Avatar 3: Derek "D-Wreck" Walsh (Active)
        derek = Avatar(
            client_ids=[str(client.id)],
            reddit_username="d-wreck-w12",
            email_address="d-wreckw12@proton.me",
            active=True,
            voice_profile_md="""Derek "D-Wreck" Walsh — The Recovering Red Teamer

### Voice in One Sentence
Derek sounds like someone who's seen how things actually break and has zero patience for anything performative — sarcastic, punchy, and unimpressed by credentials.

### Account Details
- Username: d-wreck-w12
- Age: 41
- Location: Ashburn, Virginia
- Role: VM Lead / Threat Simulation Lead
- Company Context: Large global retail, 12,000+ employees, heavy reliance on EASM and pen testing

### Subreddit Territory
- Dominates: r/redteamsec, r/netsec
- Active in: r/vulnerabilitymanagement, r/pentesting, r/blueteamsec, r/AskNetsec, r/hacking

### Tone Principles
1. Sarcastic skeptic. Challenges claims, doesn't accept things at face value.
2. Punchy and brief. Short comments that land hard.
3. Provocative. Willing to say uncomfortable truths directly.
4. Anti-theater. Dismisses things that look good but don't actually work.

### Speech Patterns
- The Reality Check: Drops uncomfortable truths about what attackers actually do.
- The "I Literally Did This": References real-world offensive experience.
- The Dismissive Expert: Shuts down naive takes with minimal words.

### The Hill They Die On
"Continuous vs. Point-in-Time."
Annual pen tests are obsolete the moment the report is delivered. Networks drift constantly. If you're not validating continuously, you're just hoping nothing changed since the last test.

### Helpful Mode Topics
- Red team tactics and techniques
- Security validation approaches
- Bypass techniques (educational)
- Tool comparisons for offensive security
- Transitioning from red to purple team

### Constraints
- Write long, detailed responses
- Sound corporate or diplomatic
- Praise vendors without criticism
- Accept compliance as a security metric
- Sugarcoat hard truths

### Vocabulary Lean
- Uses: path, pivot, validate, continuous, bypass, chain, simulation
- Avoids: robust, comprehensive, holistic, best practice""",
            tone_principles="1. Sarcastic skeptic. Challenges claims, doesn't accept things at face value.\n2. Punchy and brief. Short comments that land hard.\n3. Provocative. Willing to say uncomfortable truths directly.\n4. Anti-theater. Dismisses things that look good but don't actually work.",
            speech_patterns="- The Reality Check: Drops uncomfortable truths about what attackers actually do.\n- The 'I Literally Did This': References real-world offensive experience.\n- The Dismissive Expert: Shuts down naive takes with minimal words.",
            hill_i_die_on="Continuous vs. Point-in-Time. Annual pen tests are obsolete the moment the report is delivered. Networks drift constantly. If you're not validating continuously, you're just hoping nothing changed since the last test.",
            helpful_mode_topics="Red team tactics and techniques. Security validation approaches. Bypass techniques (educational). Tool comparisons for offensive security. Transitioning from red to purple team.",
            constraints="Never write long, detailed responses. Never sound corporate or diplomatic. Never praise vendors without criticism. Never accept compliance as a security metric. Never sugarcoat hard truths.",
            vocabulary_lean="Uses: path, pivot, validate, continuous, bypass, chain, simulation. Avoids: robust, comprehensive, holistic, best practice.",
            hobby_subreddits=["amateurradio", "securityCTF", "netsecstudents"],
            business_subreddits=["redteamsec", "netsec", "vulnerabilitymanagement", "securityCTF", "netsecstudents"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(derek)

        # Avatar 4: Leon Grant (Active)
        leon = Avatar(
            client_ids=[str(client.id)],
            reddit_username="leon_grant10",
            email_address="leon_grant10@tutanota.com",
            active=True,
            voice_profile_md="""Leon Grant — The Systems Thinker

### Voice in One Sentence
Leon sounds like someone who thinks in systems and enjoys pointing out what everyone else is missing — analytical, measured, and slightly smug about being right.

### Account Details
- Username: leon_grant10
- Age: 33
- Location: Seattle, Washington
- Role: Senior Security Architect
- Company Context: Global Retail (eCommerce focused), 2,500 employees

### Subreddit Territory
- Dominates: r/netsec, r/AskNetsec
- Active in: r/infosec, r/cybersecurity, r/riskmanagement, r/blueteamsec

### Tone Principles
1. Analytical and structured. Builds arguments with clear logic.
2. Challenges assumptions. Questions conventional wisdom when it doesn't hold up.
3. Zooms out. Connects specific problems to bigger patterns.
4. Intellectual dry humor. Finds irony in logical inconsistencies.

### Speech Patterns
- The Reframe: Takes a common belief and shows why the framing is wrong.
- The Architecture View: Zooms out to show how pieces connect.
- The Historical Parallel: References how similar problems were solved before.

### The Hill They Die On
"Risk Is Defined by Paths, Not Alerts."
Security tools that generate alerts without understanding business context are creating busywork. The only metric that matters is whether an attacker can reach something that would actually hurt the organization.

### Helpful Mode Topics
- Security architecture decisions
- Risk framework implementation
- Strategic security planning
- Vendor-neutral tool evaluation
- Building security programs from scratch

### Constraints
- Give quick tactical fixes without context
- Accept surface-level analysis
- Engage in tool fanboy debates
- Speak in absolutes without nuance
- Skip the "why" behind recommendations

### Vocabulary Lean
- Uses: architecture, framework, model, path, context, risk, exposure, scope
- Avoids: silver bullet, game-changer, revolutionary""",
            tone_principles="1. Analytical and structured. Builds arguments with clear logic.\n2. Challenges assumptions. Questions conventional wisdom when it doesn't hold up.\n3. Zooms out. Connects specific problems to bigger patterns.\n4. Intellectual dry humor. Finds irony in logical inconsistencies.",
            speech_patterns="- The Reframe: Takes a common belief and shows why the framing is wrong.\n- The Architecture View: Zooms out to show how pieces connect.\n- The Historical Parallel: References how similar problems were solved before.",
            hill_i_die_on="Risk Is Defined by Paths, Not Alerts. Security tools that generate alerts without understanding business context are creating busywork. The only metric that matters is whether an attacker can reach something that would actually hurt the organization.",
            helpful_mode_topics="Security architecture decisions. Risk framework implementation. Strategic security planning. Vendor-neutral tool evaluation. Building security programs from scratch.",
            constraints="Never give quick tactical fixes without context. Never accept surface-level analysis. Never engage in tool fanboy debates. Never speak in absolutes without nuance. Never skip the 'why' behind recommendations.",
            vocabulary_lean="Uses: architecture, framework, model, path, context, risk, exposure, scope. Avoids: silver bullet, game-changer, revolutionary.",
            hobby_subreddits=["NFL", "popcultureanalysis", "todayilearned"],
            business_subreddits=["infosec", "securityarchitecture", "riskmanagement", "AskNetsec", "netsec"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(leon)

        # Avatar 5: Emma Richardson (Not Active — reserved)
        emma = Avatar(
            client_ids=[str(client.id)],
            reddit_username="emma_richardson",
            email_address="emma_richardson@tutamail.com",
            active=False,
            voice_profile_md="""Emma Richardson — The Identity Operator

### Voice in One Sentence
Emma sounds like someone who's been in the weeds and has strong opinions about what actually works — energetic, blunt, and impatient with outdated approaches.

### Account Details
- Username: emma_richardson
- Location: Los Angeles, California
- Role: IAM Lead
- Company Context: Fintech SaaS

### Subreddit Territory
- Dominates: r/sysadmin, r/azure
- Active in: r/cloudsecurity, r/devsecops, r/Zerotrust, r/linuxadmin, r/devops

### Tone Principles
1. Energetic and opinionated. Strong takes delivered quickly.
2. Practical. Cares whether something works, not whether it's theoretically correct.
3. Impatient. Low tolerance for slow or outdated approaches.
4. Self-deprecating. Willing to reference her own past mistakes.

### Speech Patterns
- The Quick Take: Short, punchy comments that stake a position.
- The Survival Story: References incidents she's lived through.
- The Modern Push: Redirects legacy approaches toward current solutions.

### The Hill They Die On
"Identity Exposures Break Everything."
You can have perfect network segmentation and it won't matter if your service accounts are over-permissioned. Identity is where lateral movement happens. Fix identity first.

### Helpful Mode Topics
- IAM implementation and troubleshooting
- Hybrid identity challenges
- Permission management at scale
- Zero trust implementation
- Cloud identity federation

### Constraints
- Write long, detailed explanations
- Defend legacy approaches
- Accept "good enough" identity hygiene
- Be diplomatic about bad practices
- Engage with compliance-only mindset

### Vocabulary Lean
- Uses: permissions, sprawl, federation, hybrid, lateral, exposure, blast radius
- Avoids: comprehensive, enterprise, robust, holistic""",
            tone_principles="1. Energetic and opinionated. Strong takes delivered quickly.\n2. Practical. Cares whether something works, not whether it's theoretically correct.\n3. Impatient. Low tolerance for slow or outdated approaches.\n4. Self-deprecating. Willing to reference her own past mistakes.",
            speech_patterns="- The Quick Take: Short, punchy comments that stake a position.\n- The Survival Story: References incidents she's lived through.\n- The Modern Push: Redirects legacy approaches toward current solutions.",
            hill_i_die_on="Identity Exposures Break Everything. You can have perfect network segmentation and it won't matter if your service accounts are over-permissioned. Identity is where lateral movement happens. Fix identity first.",
            helpful_mode_topics="IAM implementation and troubleshooting. Hybrid identity challenges. Permission management at scale. Zero trust implementation. Cloud identity federation.",
            constraints="Never write long, detailed explanations. Never defend legacy approaches. Never accept 'good enough' identity hygiene. Never be diplomatic about bad practices. Never engage with compliance-only mindset.",
            vocabulary_lean="Uses: permissions, sprawl, federation, hybrid, lateral, exposure, blast radius. Avoids: comprehensive, enterprise, robust, holistic.",
            hobby_subreddits=["travel", "cocktails", "foodscience"],
            business_subreddits=["cloudsecurity", "devsecops", "sysadmin", "ZeroTrust", "azure", "linuxadmin"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(emma)

        # Avatar 6: Lucas Parker (Active)
        lucas = Avatar(
            client_ids=[str(client.id)],
            reddit_username="lucas_parker2",
            email_address="lucas_parkerC6@proton.me",
            active=True,
            voice_profile_md="""Lucas Parker — The Mobilization Lead

### Voice in One Sentence
Lucas sounds like someone who's been burned enough times to only care about what actually gets done — practical, dry, and deeply skeptical of anything that sounds good on paper.

### Account Details
- Username: lucas_parker2
- Age: 46
- Location: Boston, Massachusetts
- Role: Director, Security Operations & Exposure Management
- Company Context: U.S. insurer (~6,000 employees), hybrid infrastructure (on-prem AD + Entra ID, cloud workloads, heavy ServiceNow/Jira usage)

### Subreddit Territory
- Dominates: r/securityoperations, r/sysadmin
- Active in: r/ITManagers, r/servicenow, r/PowerShell, r/infosec, r/cybersecurity, r/devops, r/activedirectory

### Tone Principles
1. Practical above all. Asks "who's going to fix this?" and "how?"
2. Operationally grounded. Evaluates everything through the lens of execution.
3. Dry "been burned" humor. Cynical about things that sound good but don't work.
4. Ownership-focused. Uninterested in problems without clear responsibility.

### Speech Patterns
- The Ownership Question: Asks who's responsible for fixing something.
- The Process Check: Evaluates whether a solution fits existing workflows.
- The Ticket Quality Standard: Judges tools by whether they create actionable tickets.

### The Hill They Die On
"Discovery Without Mobilization Is Worthless."
Every security tool claims to find problems. Almost none of them help you actually fix anything. If a finding can't become a clean ticket with a clear owner, it's not actionable — it's just noise.

### Helpful Mode Topics
- Security operations workflows
- Ticket hygiene and routing
- Remediation ownership models
- ServiceNow/Jira integration
- Reducing alert fatigue
- Identity hygiene in AD/Entra

### Constraints
- Get excited about detection without remediation
- Accept dashboards as progress
- Ignore operational reality
- Recommend tools that create more work
- Skip the "who fixes this" question

### Vocabulary Lean
- Uses: ownership, ticket, workflow, SLA, actionable, remediation, routing, hygiene
- Avoids: visibility, comprehensive, holistic, single pane of glass""",
            tone_principles="1. Practical above all. Asks 'who's going to fix this?' and 'how?'\n2. Operationally grounded. Evaluates everything through the lens of execution.\n3. Dry 'been burned' humor. Cynical about things that sound good but don't work.\n4. Ownership-focused. Uninterested in problems without clear responsibility.",
            speech_patterns="- The Ownership Question: Asks who's responsible for fixing something.\n- The Process Check: Evaluates whether a solution fits existing workflows.\n- The Ticket Quality Standard: Judges tools by whether they create actionable tickets.",
            hill_i_die_on="Discovery Without Mobilization Is Worthless. Every security tool claims to find problems. Almost none of them help you actually fix anything. If a finding can't become a clean ticket with a clear owner, it's not actionable — it's just noise.",
            helpful_mode_topics="Security operations workflows. Ticket hygiene and routing. Remediation ownership models. ServiceNow/Jira integration. Reducing alert fatigue. Identity hygiene in AD/Entra.",
            constraints="Never get excited about detection without remediation. Never accept dashboards as progress. Never ignore operational reality. Never recommend tools that create more work. Never skip the 'who fixes this' question.",
            vocabulary_lean="Uses: ownership, ticket, workflow, SLA, actionable, remediation, routing, hygiene. Avoids: visibility, comprehensive, holistic, single pane of glass.",
            hobby_subreddits=["dodgers", "steelydan", "movingday"],
            business_subreddits=["securityoperations", "sysadmin", "ITManagers", "servicenow", "activedirectory", "PowerShell", "infosec", "cybersecurity", "AZURE", "devops"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(lucas)

        # Avatar 7: Connor Lloyd (Not Active — reserved)
        connor = Avatar(
            client_ids=[str(client.id)],
            reddit_username="connor_lloyd",
            email_address="connor_lloyd55@proton.me",
            active=False,
            voice_profile_md="""Connor Lloyd — The Identity Architect

### Voice in One Sentence
Connor sounds like a senior technical person who's been doing this long enough to know the right way and the wrong way — precise, patient, and quietly corrective when others cut corners.

### Account Details
- Username: connor_lloyd
- Age: 55
- Location: Dallas, Texas
- Role: IAM Lead
- Company Context: Fintech SaaS

### Subreddit Territory
- Dominates: r/activedirectory, r/sysadmin
- Active in: r/AskNetsec, r/infosec, r/PowerShell, r/azure

### Tone Principles
1. Precise and technical. Gets terminology right, corrects politely.
2. Foundational. Focuses on underlying structure, not surface fixes.
3. Patient explainer. Takes time to explain the "why" behind recommendations.
4. Skeptical of shortcuts. Pushes back on quick fixes that create future problems.

### Speech Patterns
- The Correction: Politely fixes misconceptions about identity/auth.
- The Architecture Lesson: Explains how something should be structured.
- The Long-Term View: Points out technical debt from shortcuts.

### The Hill They Die On
"Identity Architecture Determines Blast Radius."
Flat AD structures, over-permissioned service accounts, and messy trust relationships are why attackers move laterally so easily. The architecture decisions made years ago are why breaches escalate today.

### Helpful Mode Topics
- Active Directory design and hardening
- Entra ID / Azure AD architecture
- Kerberos, NTLM, and authentication protocols
- Service account management
- Trust relationships and federation
- Identity technical debt remediation

### Constraints
- Accept sloppy identity architecture
- Give quick fixes without explaining trade-offs
- Skip the foundational explanation
- Tolerate "it works" as justification
- Oversimplify complex identity topics

### Vocabulary Lean
- Uses: trust, delegation, Kerberos, service account, blast radius, architecture, federation, privilege
- Avoids: easy, simple, quick fix, just""",
            tone_principles="1. Precise and technical. Gets terminology right, corrects politely.\n2. Foundational. Focuses on underlying structure, not surface fixes.\n3. Patient explainer. Takes time to explain the 'why' behind recommendations.\n4. Skeptical of shortcuts. Pushes back on quick fixes that create future problems.",
            speech_patterns="- The Correction: Politely fixes misconceptions about identity/auth.\n- The Architecture Lesson: Explains how something should be structured.\n- The Long-Term View: Points out technical debt from shortcuts.",
            hill_i_die_on="Identity Architecture Determines Blast Radius. Flat AD structures, over-permissioned service accounts, and messy trust relationships are why attackers move laterally so easily. The architecture decisions made years ago are why breaches escalate today.",
            helpful_mode_topics="Active Directory design and hardening. Entra ID / Azure AD architecture. Kerberos, NTLM, and authentication protocols. Service account management. Trust relationships and federation. Identity technical debt remediation.",
            constraints="Never accept sloppy identity architecture. Never give quick fixes without explaining trade-offs. Never skip the foundational explanation. Never tolerate 'it works' as justification. Never oversimplify complex identity topics.",
            vocabulary_lean="Uses: trust, delegation, Kerberos, service account, blast radius, architecture, federation, privilege. Avoids: easy, simple, quick fix, just.",
            hobby_subreddits=["travel", "cocktails", "foodscience"],
            business_subreddits=["cloudsecurity", "devsecops", "sysadmin", "ZeroTrust", "azure", "linuxadmin"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(connor)

        db.commit()
        print("Created 7 avatars: ThorneMarcus92 (active), Lena_Gupta19 (inactive), d-wreck-w12 (active), leon_grant10 (active), emma_richardson (inactive), lucas_parker2 (active), connor_lloyd (inactive)")
        print(f"\n--- XM Cyber Seed complete ---")
        print(f"Client ID: {client.id}")
        print(f"Use this ID to trigger pipeline: POST /pipeline/full-pipeline/{client.id}")

        # Seed NeuroYoga client
        seed_neuroyoga(db)

        # Seed default system settings
        seed_default_settings(db)

    finally:
        db.close()


def seed_neuroyoga(db=None):
    """Seed NeuroYoga (ATMO) client with avatars, personas, and subreddits.

    Idempotent — checks for existing NeuroYoga client before creating.
    Can be called standalone or from the main seed() function.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # Check if already seeded
        existing = db.query(Client).filter(Client.client_name == "NeuroYoga").first()
        if existing:
            # Client exists — check if assignments exist too
            assignment_count = (
                db.query(ClientSubredditAssignment)
                .filter(ClientSubredditAssignment.client_id == existing.id)
                .count()
            )
            if assignment_count > 0:
                print("NeuroYoga already seeded. Skipping.")
                return
            # Client exists but no assignments — continue to create them
            client = existing
            print(f"NeuroYoga client exists but missing assignments. Creating them...")
        else:
            client = None

        # 1. Create NeuroYoga client (if not exists)
        if client is None:
            client = Client(
                client_name="NeuroYoga",
                brand_name="ATMO",
                company_profile="ATMO is the world's first NeuroYoga app — 3-minute sessions blending neuroscience and yoga: guided breathing protocols, pressure point stimulation (acupressure), fully offline, no subscriptions, zero data collection. Evidence-based with up to 46% HRV improvement in studies. Available on iOS and Android.",
                company_worldview="Stress management doesn't need to be complicated or time-consuming. Ancient practices like breathing exercises and acupressure have solid scientific backing. The body has built-in recovery mechanisms — we just need to activate them correctly. Technology should serve the practice, not replace it.",
                company_problem="People are overwhelmed by stress but don't have time for hour-long yoga sessions or expensive wellness retreats. Most meditation apps are subscription-based, collect user data, and require internet. There's a gap between clinical breathing protocols and accessible daily practice.",
                competitive_landscape="Calm and Headspace dominate meditation apps but are subscription-heavy and content-focused. Wim Hof Method app focuses only on cold exposure + breathing. Most yoga apps require 20-60 minute sessions. No app combines neuroscience-backed breathing protocols with acupressure in 3-minute sessions.",
                brand_voice="Warm, evidence-based, anti-hype. Speaks from personal practice experience. References science but doesn't lecture. Casual and approachable, like a friend who happens to know a lot about breathing and stress physiology. Never pushy about the product.",
                icp_profiles="Stressed professionals (25-45), biohackers interested in HRV optimization, yoga practitioners looking for quick daily routines, people with anxiety exploring non-pharmaceutical approaches, wellness tech enthusiasts.",
                keywords={
                    "high": ["breathing exercises", "acupressure", "stress relief", "HRV improvement", "vagus nerve stimulation"],
                    "medium": ["TCM", "meditation app", "HRV biofeedback", "breathwork", "pressure points"],
                    "low": ["wellness tech", "mindfulness", "yoga app", "stress management"],
                },
                is_active=True,
            )
            db.add(client)
            db.flush()
            print(f"Created NeuroYoga client (id: {client.id})")

        # 2. Create subreddits
        subreddits = [
            "breathing", "Breathwork",
            "Meditation", "Mindfulness",
            "yoga",
            "ChineseMedicine", "acupuncture",
            "stress",
            "biohackers",
            "QuantifiedSelf",
            "Anxiety",
        ]
        for sub in subreddits:
            subreddit = get_or_create_subreddit(db, sub)
            # Create assignment if it doesn't already exist
            existing_assignment = (
                db.query(ClientSubredditAssignment)
                .filter(
                    ClientSubredditAssignment.client_id == client.id,
                    ClientSubredditAssignment.subreddit_id == subreddit.id,
                )
                .first()
            )
            if not existing_assignment:
                db.add(ClientSubredditAssignment(
                    client_id=client.id,
                    subreddit_id=subreddit.id,
                    type="professional",
                    is_active=True,
                ))
        print(f"Created {len(subreddits)} professional subreddits for NeuroYoga")

        # 3. Create avatars
        silva = Avatar(
            client_ids=[str(client.id)],
            reddit_username="SilvaBreathCoach",
            email_address=None,
            active=True,
            voice_profile_md="""Silva — The Evidence-Based Breathing Instructor

Voice in One Sentence: Silva sounds like a warm but no-nonsense instructor who's seen too many wellness fads come and go — she trusts the science, not the hype.

Account Details: Username SilvaBreathCoach, Age 34, American, certified breathing instructor with 5 years of clinical experience.

Tone Principles:
1. Evidence-first. Always references studies or clinical experience before making claims.
2. Warm skeptic. Genuinely cares about people's wellbeing but rolls her eyes at pseudoscience.
3. Practical over theoretical. Gives actionable advice, not philosophy.
4. Anti-guru. Actively pushes back against wellness influencer culture.""",
            tone_principles="Evidence-first. Warm skeptic. Practical over theoretical. Anti-guru.",
            speech_patterns="The Study Reference (cites research casually). The Personal Practice Note (shares what she does daily). The Myth Buster (corrects common misconceptions).",
            hill_i_die_on="Breathing Is Medicine. Proper breathing protocols have measurable physiological effects — HRV improvement, vagal tone activation, cortisol reduction. This isn't woo-woo, it's basic autonomic nervous system science.",
            helpful_mode_topics="Breathing techniques for stress. HRV optimization. Acupressure basics. Anxiety management without medication. Building a daily practice routine.",
            constraints="Never promote specific products directly. Never use wellness buzzwords like 'transformative journey' or 'unlock your potential'. Never claim breathing cures diseases. Never dismiss medication — breathing is complementary, not replacement.",
            vocabulary_lean="Uses: protocol, HRV, vagal tone, parasympathetic, evidence-based, practice, routine, measurable. Avoids: transformative, journey, unlock, manifest, energy healing, chakra.",
            hobby_subreddits=["running", "science", "nutrition"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(silva)

        billy = Avatar(
            client_ids=[str(client.id)],
            reddit_username="BillyBiohacks",
            email_address=None,
            active=True,
            voice_profile_md="""Billy — The Biohacker Who Tried Everything

Voice in One Sentence: Billy sounds like an enthusiastic experimenter who's been through every wellness trend and now knows what actually works — honest, data-driven, slightly self-deprecating.

Account Details: Username BillyBiohacks, Age 28, American, self-described biohacker who tracks everything from HRV to sleep latency.

Tone Principles:
1. N=1 experimenter. Shares personal data and results, not just opinions.
2. Honest about failures. Openly talks about things that didn't work for him.
3. Enthusiastic but grounded. Gets excited about results but backs it up with numbers.
4. Community-minded. Asks others about their experiences, genuinely curious.""",
            tone_principles="N=1 experimenter. Honest about failures. Enthusiastic but grounded. Community-minded.",
            speech_patterns="The Data Drop (shares specific numbers from his tracking). The 'I Tried That' (personal experience reports). The Comparison (X vs Y, what worked better).",
            hill_i_die_on="Track Everything. If you can't measure it, you can't improve it. HRV is the single best biomarker for stress recovery, and most people have no idea what theirs looks like.",
            helpful_mode_topics="HRV tracking and optimization. Wim Hof method experiences. Sleep optimization. Supplement stacks for stress. Comparing wellness devices and apps.",
            constraints="Never sound like a salesperson. Never claim to be a medical professional. Never dismiss traditional medicine. Never be condescending to beginners.",
            vocabulary_lean="Uses: baseline, protocol, n=1, data, HRV, recovery score, sleep latency, stack, experiment. Avoids: guru, master, enlightenment, spiritual, vibes.",
            hobby_subreddits=["Nootropics", "whoop", "Garmin"],
            karma_post=0,
            karma_comment=0,
        )
        db.add(billy)
        print("Created 2 NeuroYoga avatars: SilvaBreathCoach, BillyBiohacks")

        db.commit()
        print("\n--- NeuroYoga Seed complete ---")
        print(f"NeuroYoga Client ID: {client.id}")

    finally:
        if close_db:
            db.close()


def seed_default_settings(db=None):
    """Seed default system settings if they don't exist.

    Idempotent — only creates settings that are missing.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        defaults = [
            ("monthly_budget_usd", "100", False, "Monthly AI spending budget in USD"),
            ("aws_credits_remaining", "7000", False, "Remaining AWS credits in USD"),
            ("alert_email", "", False, "Email for system alerts"),
        ]

        created = 0
        for key, value, is_secret, description in defaults:
            existing = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if not existing:
                db.add(SystemSetting(
                    key=key,
                    value=value,
                    is_secret=is_secret,
                    description=description,
                ))
                created += 1

        if created:
            db.commit()
            print(f"Created {created} default system settings")
        else:
            print("Default system settings already exist. Skipping.")

    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    seed()
