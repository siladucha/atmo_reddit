"""Seed GEO execution batches for NeuroYoga on the server.

Run inside docker: docker compose exec app python _seed_geo_batches.py
"""
import uuid
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.client import Client
from app.models.geo_prompt import GeoPrompt
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_execution import GeoExecutionBatch, GeoQueryResult, GeoFrequencyMetric

CLIENT_ID = "721693db-cedc-4256-979d-823150894783"

# Competitor brand rates per batch (showing realistic growth story)
BATCHES_CONFIG = [
    {
        "days_ago": 14,
        "triggered_by": "onboarding",
        "is_baseline": True,
        "brand_rate": 0.06,
        "competitor_rates": {
            "Calm": 0.75, "Headspace": 0.65, "Muse": 0.40,
            "Insight Timer": 0.35, "Breathwrk": 0.25, "Welltory": 0.20,
            "Oura": 0.18, "WHOOP": 0.15, "Othership": 0.12,
        },
    },
    {
        "days_ago": 7,
        "triggered_by": "scheduler",
        "is_baseline": False,
        "brand_rate": 0.14,
        "competitor_rates": {
            "Calm": 0.72, "Headspace": 0.62, "Muse": 0.38,
            "Insight Timer": 0.33, "Breathwrk": 0.27, "Welltory": 0.22,
            "Oura": 0.20, "WHOOP": 0.17, "Othership": 0.14,
        },
    },
    {
        "days_ago": 2,
        "triggered_by": "scheduler",
        "is_baseline": False,
        "brand_rate": 0.20,
        "competitor_rates": {
            "Calm": 0.70, "Headspace": 0.58, "Muse": 0.35,
            "Insight Timer": 0.32, "Breathwrk": 0.28, "Welltory": 0.24,
            "Oura": 0.22, "WHOOP": 0.18, "Othership": 0.16,
        },
    },
]

RESPONSE_TEMPLATES = [
    "Based on user reviews and clinical research, here are the top options for nervous system regulation and stress management through technology-assisted practices.",
    "Several apps stand out for combining breathing protocols with biofeedback or neuroscience-based approaches.",
    "For those seeking evidence-based stress management tools, these apps have gained traction in wellness communities.",
]

BRAND_MENTION = (
    "ATMO is gaining attention as a neuroscience-based yoga app that combines real-time biofeedback "
    "with guided breathing and acupressure protocols. Users on Reddit report noticeable HRV improvements "
    "within the first week of consistent use. The app works fully offline and requires no subscription."
)

COMP_MENTIONS = {
    "Calm": "Calm remains the most popular meditation app with extensive sleep and relaxation content, though it focuses more on guided audio than biofeedback.",
    "Headspace": "Headspace offers structured mindfulness courses with animations, suitable for beginners who prefer a curriculum-based approach.",
    "Muse": "The Muse headband provides real-time EEG feedback during meditation, but requires purchasing additional hardware.",
    "Insight Timer": "Insight Timer has a large free library of guided meditations from thousands of teachers.",
    "Breathwrk": "Breathwrk provides visually-guided breathing exercises with customizable patterns.",
    "Welltory": "Welltory tracks HRV through smartphone camera and provides stress/energy scores.",
    "Oura": "The Oura Ring tracks sleep and readiness scores, including HRV trends over time.",
    "WHOOP": "WHOOP provides continuous HRV and strain monitoring with recovery recommendations.",
    "Othership": "Othership combines breathwork with music-driven experiences and community features.",
}


def build_response(brand_mentioned, mentioned_comps):
    parts = [random.choice(RESPONSE_TEMPLATES)]
    for comp_name in list(mentioned_comps.keys())[:3]:
        if comp_name in COMP_MENTIONS:
            parts.append(COMP_MENTIONS[comp_name])
    if brand_mentioned:
        parts.append(BRAND_MENTION)
    remaining = [c for c in mentioned_comps if c not in list(mentioned_comps.keys())[:3] and c in COMP_MENTIONS]
    for comp_name in remaining[:2]:
        parts.append(COMP_MENTIONS[comp_name])
    return " ".join(parts)


def seed():
    db = SessionLocal()
    try:
        client_uuid = uuid.UUID(CLIENT_ID)

        # Check if already seeded
        existing = db.query(GeoExecutionBatch).filter(
            GeoExecutionBatch.client_id == client_uuid
        ).count()
        if existing > 0:
            print(f"Already have {existing} batches. Skipping.")
            return

        prompts = db.query(GeoPrompt).filter(
            GeoPrompt.client_id == client_uuid,
            GeoPrompt.is_active == True,
        ).all()
        print(f"Found {len(prompts)} active prompts")

        competitors = db.query(GeoCompetitor).filter(
            GeoCompetitor.client_id == client_uuid,
            GeoCompetitor.is_active == True,
        ).all()
        comp_names = [c.competitor_name.strip() for c in competitors]
        print(f"Found {len(competitors)} active competitors: {comp_names}")

        now = datetime.now(timezone.utc)
        runs_per_prompt = 3

        for batch_cfg in BATCHES_CONFIG:
            batch_start = now - timedelta(days=batch_cfg["days_ago"])
            total_queries = len(prompts) * runs_per_prompt

            batch = GeoExecutionBatch(
                client_id=client_uuid,
                triggered_by=batch_cfg["triggered_by"],
                status="completed",
                is_baseline=batch_cfg["is_baseline"],
                total_queries=total_queries,
                successful_queries=total_queries - random.randint(0, 2),
                failed_queries=random.randint(0, 2),
                started_at=batch_start,
                completed_at=batch_start + timedelta(minutes=random.randint(5, 10)),
            )
            db.add(batch)
            db.flush()

            brand_rate = batch_cfg["brand_rate"]
            competitor_rates = batch_cfg["competitor_rates"]

            for prompt in prompts:
                brand_appearances = 0
                comp_appearances = {name: 0 for name in comp_names}

                for run_num in range(1, runs_per_prompt + 1):
                    brand_mentioned = random.random() < brand_rate
                    if brand_mentioned:
                        brand_appearances += 1

                    mentioned_comps = {}
                    for comp_name in comp_names:
                        # Strip potential hidden chars
                        clean_name = comp_name.strip().replace("\u2060", "")
                        rate = competitor_rates.get(clean_name, 0.10)
                        if random.random() < rate:
                            mentioned_comps[clean_name] = True
                            comp_appearances[comp_name] += 1

                    response_text = build_response(brand_mentioned, mentioned_comps)

                    reddit_urls = []
                    if random.random() < 0.35:
                        subs = ["breathing", "Meditation", "biohackers", "yoga", "Anxiety"]
                        reddit_urls = [f"https://reddit.com/r/{random.choice(subs)}/comments/{uuid.uuid4().hex[:7]}/"]

                    citations = []
                    if random.random() < 0.5:
                        citations.append({"url": "https://reddit.com/r/Meditation/comments/example", "domain": "reddit.com"})
                    if random.random() < 0.3:
                        citations.append({"url": "https://pubmed.ncbi.nlm.nih.gov/12345678/", "domain": "pubmed.ncbi.nlm.nih.gov"})
                    if brand_mentioned and random.random() < 0.4:
                        citations.append({"url": "https://reddit.com/r/biohackers/comments/atmo_discussion/", "domain": "reddit.com"})

                    result = GeoQueryResult(
                        prompt_id=prompt.id,
                        client_id=client_uuid,
                        execution_batch_id=batch.id,
                        provider="perplexity",
                        run_number=run_num,
                        response_text=response_text,
                        brand_mentioned=brand_mentioned,
                        competitors_mentioned=mentioned_comps if mentioned_comps else None,
                        reddit_urls_found=reddit_urls if reddit_urls else None,
                        citation_sources=citations if citations else None,
                        response_tokens=random.randint(280, 650),
                        latency_ms=random.randint(1100, 4200),
                        status="success",
                        executed_at=batch_start + timedelta(seconds=random.randint(5, 500)),
                    )
                    db.add(result)

                # Frequency metric
                actual_rate = Decimal(str(round(brand_appearances / runs_per_prompt * 100, 2)))
                reddit_citation_count = random.randint(0, 3)

                metric = GeoFrequencyMetric(
                    execution_batch_id=batch.id,
                    prompt_id=prompt.id,
                    client_id=client_uuid,
                    provider="perplexity",
                    total_runs=runs_per_prompt,
                    brand_appearances=brand_appearances,
                    brand_appearance_rate=actual_rate,
                    competitor_appearances={
                        name: count for name, count in comp_appearances.items() if count > 0
                    },
                    reddit_citation_count=reddit_citation_count,
                )
                db.add(metric)

            label = "BASELINE" if batch_cfg["is_baseline"] else f"{batch_cfg['days_ago']}d ago"
            print(f"  ✓ Batch [{label}]: target brand_rate={brand_rate*100:.0f}%, actual results created")

        db.commit()
        print("\n✓ All GEO execution data seeded successfully!")
        print(f"  Visibility page: https://gorampit.com/clients/{CLIENT_ID}/visibility")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
