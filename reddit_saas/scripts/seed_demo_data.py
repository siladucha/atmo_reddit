"""Seed realistic demo data for client portal demonstration.

Creates posted comments with karma scores, varied dates, and realistic content
to make the Report/Insights page look populated and professional.

Usage:
    cd reddit_saas
    python -m scripts.seed_demo_data

Requires: running PostgreSQL (local or Docker).
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.database import SessionLocal
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.subreddit import Subreddit, ClientSubredditAssignment
from app.models.thread import RedditThread


# --- Demo comment content (realistic, varied) ---

DEMO_COMMENTS = [
    {
        "subreddit": "cybersecurity",
        "title": "What's your take on attack path management vs traditional vuln scanning?",
        "body": "We've been using Qualys for years but I keep hearing about attack path analysis. Is it worth the switch?",
        "comment": "Traditional vuln scanning gives you a list of 10,000 CVEs. Attack path analysis shows you which 12 of those actually lead to your crown jewels. Completely different mental model — one is a checklist, the other is a map.",
        "approach": "reframe_drop",
        "score": 47,
    },
    {
        "subreddit": "netsec",
        "title": "How do you prioritize patching when everything is 'critical'?",
        "body": "Our security team is drowning. 3000+ critical vulns, 4 people. Help.",
        "comment": "Context is everything. A critical CVE on an isolated dev box with no path to prod is noise. A medium-severity misconfiguration that chains into domain admin access is a five-alarm fire. The severity score alone tells you almost nothing about actual risk.",
        "approach": "the_scar",
        "score": 34,
    },
    {
        "subreddit": "AskNetsec",
        "title": "Identity-based attacks seem to be everywhere now. What changed?",
        "body": "Seeing way more credential-based breaches in the news. Is this a new trend or just better reporting?",
        "comment": "It's not new — it's just that attackers realized why bother exploiting a zero-day when you can just log in? Stolen creds, misconfigured service accounts, overprivileged identities. The identity layer is the new perimeter and most orgs still treat it like an afterthought.",
        "approach": "contrarian",
        "score": 28,
    },
    {
        "subreddit": "sysadmin",
        "title": "AD security — where do you even start?",
        "body": "Inherited a 15-year-old AD environment. It's a mess. Looking for practical first steps.",
        "comment": "Start with the blast radius question: if one account gets compromised, how far can an attacker move? Map your tier-0 assets, check for kerberoastable accounts, and look at who has DCSync rights. You'll probably find 3-4 things that make you lose sleep immediately.",
        "approach": "drive_by",
        "score": 52,
    },
    {
        "subreddit": "blueteam",
        "title": "How do you explain security ROI to the board?",
        "body": "Board wants numbers. 'We didn't get breached' isn't compelling enough apparently.",
        "comment": "Frame it as risk reduction, not prevention. Show them: 'Last quarter we had 47 exploitable paths to critical assets. This quarter we have 8. Here's what we fixed and what it would have cost if exploited.' Boards understand graphs that go down.",
        "approach": "reframe_drop",
        "score": 63,
    },
    {
        "subreddit": "cybersecurity",
        "title": "CTEM vs traditional pen testing — is continuous better?",
        "body": "Our annual pen test always finds the same stuff. Thinking about continuous threat exposure management.",
        "comment": "Annual pen tests are like checking your locks once a year. Your environment changes daily — new cloud resources, new identities, new misconfigurations. By the time you get the report, half the findings are stale and new exposures have appeared. Continuous validation catches drift.",
        "approach": "the_scar",
        "score": 41,
    },
    {
        "subreddit": "CloudSecurity",
        "title": "Multi-cloud visibility is killing us. Anyone solved this?",
        "body": "AWS + Azure + some GCP. Three different security tools, three different dashboards. No unified view.",
        "comment": "The real problem isn't visibility — it's that each cloud has different identity models, different permission structures, and different ways things can go wrong. A misconfiguration in Azure AD can create an attack path through AWS via federated trust. You need to think in graphs, not silos.",
        "approach": "contrarian",
        "score": 19,
    },
    {
        "subreddit": "netsec",
        "title": "What's the most underrated security risk in enterprise environments?",
        "body": "Looking for things that fly under the radar but have massive impact.",
        "comment": "Lateral movement via misconfigured service accounts. Everyone focuses on the perimeter, but once inside, the average enterprise has dozens of overprivileged service accounts that haven't been rotated in years. One compromised endpoint + one stale service account = domain admin in 3 hops.",
        "approach": "drive_by",
        "score": 71,
    },
    {
        "subreddit": "sysadmin",
        "title": "How do you handle security when your team is understaffed?",
        "body": "2 people managing security for 5000 endpoints. We can't do everything.",
        "comment": "Focus on what actually matters: which vulnerabilities are exploitable AND reachable from the internet AND lead to critical assets? That's usually 2-3% of your total vuln count. Fix those first. The other 97% can wait — attackers won't use them because they don't lead anywhere useful.",
        "approach": "reframe_drop",
        "score": 38,
    },
    {
        "subreddit": "cybersecurity",
        "title": "Digital twin technology for security — hype or real?",
        "body": "Seeing vendors talk about 'digital twins' of your environment. Sounds like marketing speak.",
        "comment": "The concept is sound even if the marketing is overblown. If you can model your entire environment — identities, permissions, network paths, vulnerabilities — and simulate attacks without touching production, you can find problems before attackers do. The question is accuracy of the model.",
        "approach": "the_scar",
        "score": 22,
    },
    {
        "subreddit": "AskNetsec",
        "title": "EDR vs XDR — is XDR actually worth the premium?",
        "body": "Our EDR works fine. Sales team pushing XDR hard. What's the real difference?",
        "comment": "EDR sees endpoints. XDR correlates across endpoints, network, identity, and cloud. The value isn't in any single detection — it's in connecting the dots. An EDR alert + an identity anomaly + a cloud permission change = a story. EDR alone just gives you the first chapter.",
        "approach": "reframe_drop",
        "score": 45,
    },
    {
        "subreddit": "blueteam",
        "title": "Attack surface management — how do you keep up with shadow IT?",
        "body": "Developers spin up cloud resources faster than we can track them. New attack surface daily.",
        "comment": "You can't win the discovery race manually. The real question is: when a new asset appears, does it automatically get assessed for exposure? If someone spins up an EC2 instance with a public IP and an IAM role that can reach your database, how long until you know? Hours? Days? Never?",
        "approach": "cynical_deconstruction",
        "score": 31,
    },
]

HOBBY_COMMENTS = [
    {
        "subreddit": "running",
        "title": "Just ran my first 10K — any tips for improving pace?",
        "comment": "Congrats on the 10K! The biggest thing that helped me was slowing down on easy runs. Sounds counterintuitive but running 80% of your miles at conversational pace builds the aerobic base that makes your fast days actually fast.",
        "score": 12,
    },
    {
        "subreddit": "Coffee",
        "title": "Pour over vs French press — which do you prefer for daily drinking?",
        "comment": "French press for weekdays when I want something forgiving and full-bodied. Pour over on weekends when I have time to dial in the technique. Different tools for different moods.",
        "score": 8,
    },
    {
        "subreddit": "homelab",
        "title": "What's everyone running on their home servers?",
        "comment": "Proxmox with a few LXC containers — Pi-hole, Jellyfin, Home Assistant, and a Wireguard VPN. Total power draw is about 35W. The Pi-hole alone was worth the setup — the difference in browsing speed is noticeable.",
        "score": 15,
    },
    {
        "subreddit": "photography",
        "title": "Street photography ethics — where do you draw the line?",
        "comment": "I follow a simple rule: if someone is clearly having a bad moment, I don't shoot. Street photography should capture life, not exploit vulnerability. That said, public spaces are public — you don't need permission for every candid.",
        "score": 6,
    },
]


def seed_demo_data():
    """Create demo posted comments with realistic karma for XM Cyber client."""
    db = SessionLocal()
    try:
        # Find XM Cyber client
        client = db.query(Client).filter(Client.client_name == "XM Cyber").first()
        if not client:
            print("ERROR: XM Cyber client not found. Run main seed first.")
            return

        # Find avatars for this client
        avatars = (
            db.query(Avatar)
            .filter(Avatar.client_ids.any(str(client.id)), Avatar.active.is_(True))
            .all()
        )
        if not avatars:
            print("ERROR: No active avatars found for XM Cyber.")
            return

        print(f"Found client: {client.client_name} (id: {client.id})")
        print(f"Found {len(avatars)} active avatars: {[a.reddit_username for a in avatars]}")

        # Get subreddit IDs
        subreddit_map = {}
        all_sub_names = set()
        for c in DEMO_COMMENTS:
            all_sub_names.add(c["subreddit"])
        for c in HOBBY_COMMENTS:
            all_sub_names.add(c["subreddit"])

        for sub_name in all_sub_names:
            sub = db.query(Subreddit).filter(func.lower(Subreddit.subreddit_name) == sub_name.lower()).first()
            if sub:
                subreddit_map[sub_name] = sub.id
            else:
                # Create subreddit if it doesn't exist
                sub = Subreddit(subreddit_name=sub_name, is_active=True)
                db.add(sub)
                db.flush()
                subreddit_map[sub_name] = sub.id
                print(f"  Created subreddit: r/{sub_name}")

        now = datetime.now(timezone.utc)
        created_threads = 0
        created_drafts = 0

        # --- Professional comments (spread over 90 days) ---
        for i, demo in enumerate(DEMO_COMMENTS):
            avatar = random.choice(avatars)
            sub_id = subreddit_map[demo["subreddit"]]

            # Spread over 90 days with some clustering
            days_ago = random.randint(1, 90)
            hours_offset = random.randint(0, 23)
            created_at = now - timedelta(days=days_ago, hours=hours_offset)
            posted_at = created_at + timedelta(hours=random.randint(2, 8))

            # Create thread
            thread = RedditThread(
                client_id=client.id,
                subreddit_id=sub_id,
                subreddit=demo["subreddit"],
                reddit_native_id=f"demo_{uuid.uuid4().hex[:8]}",
                post_title=demo["title"],
                post_body=demo.get("body", ""),
                url=f"https://reddit.com/r/{demo['subreddit']}/comments/{uuid.uuid4().hex[:6]}/",
                author=f"user_{random.randint(1000, 9999)}",
                score=random.randint(10, 500),
                ups=random.randint(10, 500),
                tag="engage",
                type="professional",
                created_at=created_at,
                scraped_at=created_at - timedelta(hours=1),
            )
            db.add(thread)
            db.flush()
            created_threads += 1

            # Create posted draft
            # Add some karma variance
            karma = demo["score"] + random.randint(-5, 10)
            if karma < 1:
                karma = 1

            draft = CommentDraft(
                thread_id=thread.id,
                client_id=client.id,
                avatar_id=avatar.id,
                type="professional",
                ai_draft=demo["comment"],
                original_ai_draft=demo["comment"],
                edited_draft=None,  # Most posted as-is
                comment_approach=demo["approach"],
                strategic_angle="authority",
                engagement_mode="professional",
                status="posted",
                posted_at=posted_at,
                created_at=created_at,
                reddit_score=karma,
                reddit_comment_url=f"https://reddit.com/r/{demo['subreddit']}/comments/{uuid.uuid4().hex[:6]}/comment/{uuid.uuid4().hex[:7]}/",
            )
            db.add(draft)
            created_drafts += 1

        # --- Hobby comments (spread over 60 days) ---
        for demo in HOBBY_COMMENTS:
            avatar = random.choice(avatars)
            sub_id = subreddit_map[demo["subreddit"]]

            days_ago = random.randint(1, 60)
            created_at = now - timedelta(days=days_ago, hours=random.randint(0, 23))
            posted_at = created_at + timedelta(hours=random.randint(1, 4))

            thread = RedditThread(
                client_id=None,  # hobby threads are not client-specific
                subreddit_id=sub_id,
                subreddit=demo["subreddit"],
                reddit_native_id=f"demo_hobby_{uuid.uuid4().hex[:8]}",
                post_title=demo["title"],
                post_body="",
                url=f"https://reddit.com/r/{demo['subreddit']}/comments/{uuid.uuid4().hex[:6]}/",
                author=f"redditor_{random.randint(100, 999)}",
                score=random.randint(5, 200),
                ups=random.randint(5, 200),
                tag="engage",
                type="hobby",
                created_at=created_at,
                scraped_at=created_at - timedelta(hours=1),
            )
            db.add(thread)
            db.flush()
            created_threads += 1

            karma = demo["score"] + random.randint(-3, 5)
            if karma < 1:
                karma = 1

            draft = CommentDraft(
                thread_id=thread.id,
                client_id=None,
                avatar_id=avatar.id,
                type="hobby",
                ai_draft=demo["comment"],
                original_ai_draft=demo["comment"],
                comment_approach="reframe_drop",
                engagement_mode="hobby",
                status="posted",
                posted_at=posted_at,
                created_at=created_at,
                reddit_score=karma,
                reddit_comment_url=f"https://reddit.com/r/{demo['subreddit']}/comments/{uuid.uuid4().hex[:6]}/comment/{uuid.uuid4().hex[:7]}/",
            )
            db.add(draft)
            created_drafts += 1

        # --- Pending drafts (for review queue demo) ---
        pending_threads_data = [
            {
                "subreddit": "cybersecurity",
                "title": "Zero trust architecture — where do you actually start implementation?",
                "body": "Everyone talks about zero trust but nobody explains the first practical step.",
                "comment": "Start with identity. Before you worry about microsegmentation or SASE, answer this: do you know exactly who has access to what, and can you verify it continuously? Most orgs can't. That's your day-one problem.",
                "approach": "reframe_drop",
            },
            {
                "subreddit": "netsec",
                "title": "Thoughts on exposure management platforms?",
                "body": "Looking at various CTEM solutions. Hard to tell marketing from substance.",
                "comment": "The litmus test: can it show you a complete attack path from initial access to critical asset, including identity hops and cloud pivots? If it only shows you vulnerabilities without context of reachability, it's just a prettier vulnerability scanner.",
                "approach": "the_scar",
            },
            {
                "subreddit": "sysadmin",
                "title": "How often do you actually test your incident response plan?",
                "body": "We have a plan on paper but never tested it. Feeling nervous.",
                "comment": "A plan you haven't tested is a wish list. Run a tabletop exercise — pick a realistic scenario (ransomware via compromised service account), walk through your response step by step. You'll find gaps in the first 10 minutes. Better to find them now than during an actual incident.",
                "approach": "drive_by",
            },
        ]

        for demo in pending_threads_data:
            avatar = random.choice(avatars)
            sub_id = subreddit_map.get(demo["subreddit"])
            if not sub_id:
                continue

            created_at = now - timedelta(hours=random.randint(2, 12))

            thread = RedditThread(
                client_id=client.id,
                subreddit_id=sub_id,
                subreddit=demo["subreddit"],
                reddit_native_id=f"demo_pending_{uuid.uuid4().hex[:8]}",
                post_title=demo["title"],
                post_body=demo.get("body", ""),
                url=f"https://reddit.com/r/{demo['subreddit']}/comments/{uuid.uuid4().hex[:6]}/",
                author=f"user_{random.randint(1000, 9999)}",
                score=random.randint(20, 300),
                ups=random.randint(20, 300),
                tag="engage",
                type="professional",
                created_at=created_at,
                scraped_at=created_at - timedelta(minutes=30),
            )
            db.add(thread)
            db.flush()
            created_threads += 1

            draft = CommentDraft(
                thread_id=thread.id,
                client_id=client.id,
                avatar_id=avatar.id,
                type="professional",
                ai_draft=demo["comment"],
                original_ai_draft=demo["comment"],
                comment_approach=demo["approach"],
                strategic_angle="authority",
                engagement_mode="professional",
                status="pending",
                created_at=created_at,
            )
            db.add(draft)
            created_drafts += 1

        db.commit()
        print(f"\n--- Demo data seeded ---")
        print(f"Created {created_threads} threads")
        print(f"Created {created_drafts} drafts ({len(DEMO_COMMENTS) + len(HOBBY_COMMENTS)} posted + {len(pending_threads_data)} pending)")
        print(f"\nPortal URL: /clients/{client.id}/report")
        print(f"Review queue: /clients/{client.id}/review")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
