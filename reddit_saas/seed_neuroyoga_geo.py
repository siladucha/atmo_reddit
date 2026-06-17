"""Seed GEO/AEO monitoring data for NeuroYoga (ATMO) client.

This script:
1. Enables geo_monitoring for the NeuroYoga client
2. Upgrades plan_type to 'growth' (fixes the 213/60 limit banner)
3. Creates 10 buyer-intent GEO prompts across categories
4. Creates 6 competitors with domains
5. Creates 3 historical GEO execution batches (baseline + 2 measurements)
   with query results and frequency metrics to populate the Visibility page

Run from reddit_saas/ directory:
    python seed_neuroyoga_geo.py
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.client import Client
from app.models.geo_prompt import GeoPrompt
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_execution import GeoExecutionBatch, GeoQueryResult, GeoFrequencyMetric


def seed_neuroyoga_geo():
    db = SessionLocal()

    try:
        # --- Find NeuroYoga client ---
        client = db.query(Client).filter(Client.client_name == "NeuroYoga").first()
        if not client:
            print("ERROR: NeuroYoga client not found. Run seed.py first.")
            return

        client_id = client.id
        print(f"Found NeuroYoga client: {client_id}")

        # --- 1. Enable GEO monitoring + upgrade plan ---
        client.geo_monitoring_enabled = True
        client.geo_execution_frequency = "twice_weekly"
        client.plan_type = "growth"
        client.max_comments_per_month = 150
        db.flush()
        print("✓ Enabled GEO monitoring, upgraded plan to 'growth' (150 actions/mo)")

        # --- 2. Create GEO Prompts ---
        prompts_data = [
            # Category: breathing
            ("What is the best breathing app for stress relief in 2026?", "breathing"),
            ("Best breathing exercises for anxiety — which apps help?", "breathing"),
            ("How to improve HRV with breathing techniques — app recommendations", "breathing"),
            # Category: wellness_tech
            ("Best biohacking apps for stress management and recovery", "wellness_tech"),
            ("Top wellness apps that actually work according to users", "wellness_tech"),
            ("What apps use vagus nerve stimulation or breathing protocols?", "wellness_tech"),
            # Category: comparison
            ("ATMO vs Calm vs Headspace — which is better for quick stress relief?", "comparison"),
            ("Best alternatives to Calm for short meditation sessions", "comparison"),
            # Category: acupressure
            ("Are there apps that teach acupressure for stress?", "acupressure"),
            ("Best acupressure and breathing combination for anxiety relief", "acupressure"),
        ]

        existing_prompts = (
            db.query(GeoPrompt)
            .filter(GeoPrompt.client_id == client_id)
            .count()
        )
        if existing_prompts >= len(prompts_data):
            print(f"✓ GEO prompts already exist ({existing_prompts}). Skipping prompt creation.")
        else:
            # Delete existing if incomplete
            if existing_prompts > 0:
                db.query(GeoPrompt).filter(GeoPrompt.client_id == client_id).delete()
                db.flush()

            prompt_objects = []
            for text, category in prompts_data:
                p = GeoPrompt(
                    client_id=client_id,
                    prompt_text=text,
                    category=category,
                    is_active=True,
                )
                db.add(p)
                prompt_objects.append(p)
            db.flush()
            print(f"✓ Created {len(prompt_objects)} GEO prompts")

        # Reload prompts (need IDs)
        prompts = db.query(GeoPrompt).filter(
            GeoPrompt.client_id == client_id, GeoPrompt.is_active == True
        ).all()

        # --- 3. Create Competitors ---
        competitors_data = [
            ("Calm", "calm.com", []),
            ("Headspace", "headspace.com", []),
            ("Wim Hof Method", "wimhofmethod.com", ["Wim Hof", "WHM"]),
            ("Breathwrk", "breathwrk.com", []),
            ("Othership", "othership.us", []),
            ("Oak Meditation", "oakmeditation.com", ["Oak"]),
        ]

        existing_comps = (
            db.query(GeoCompetitor)
            .filter(GeoCompetitor.client_id == client_id)
            .count()
        )
        if existing_comps >= len(competitors_data):
            print(f"✓ Competitors already exist ({existing_comps}). Skipping.")
        else:
            if existing_comps > 0:
                db.query(GeoCompetitor).filter(GeoCompetitor.client_id == client_id).delete()
                db.flush()

            for name, domain, aliases in competitors_data:
                comp = GeoCompetitor(
                    client_id=client_id,
                    competitor_name=name,
                    competitor_domain=domain,
                    aliases=aliases,
                    is_active=True,
                )
                db.add(comp)
            db.flush()
            print(f"✓ Created {len(competitors_data)} competitors")

        # Reload competitors
        competitors = db.query(GeoCompetitor).filter(
            GeoCompetitor.client_id == client_id, GeoCompetitor.is_active == True
        ).all()

        # --- 4. Create Historical GEO Execution Batches ---
        existing_batches = (
            db.query(GeoExecutionBatch)
            .filter(GeoExecutionBatch.client_id == client_id)
            .count()
        )
        if existing_batches > 0:
            print(f"✓ Execution batches already exist ({existing_batches}). Skipping.")
            db.commit()
            print("\n--- NeuroYoga GEO Seed complete ---")
            return

        now = datetime.now(timezone.utc)

        # --- Batch 1: Baseline (2 weeks ago) ---
        batch1_start = now - timedelta(days=14)
        batch1 = GeoExecutionBatch(
            client_id=client_id,
            triggered_by="onboarding",
            status="completed",
            is_baseline=True,
            total_queries=30,  # 10 prompts × 3 runs
            successful_queries=28,
            failed_queries=2,
            started_at=batch1_start,
            completed_at=batch1_start + timedelta(minutes=8),
        )
        db.add(batch1)
        db.flush()

        # Baseline: ATMO barely appears (5% brand rate — new brand)
        _create_batch_results(
            db, batch1, prompts, competitors, client_id,
            brand_rate=0.05,  # 5% — baseline, brand not yet known
            competitor_rates={"Calm": 0.70, "Headspace": 0.60, "Wim Hof Method": 0.35, "Breathwrk": 0.20, "Othership": 0.10, "Oak Meditation": 0.08},
            base_time=batch1_start,
        )
        print(f"✓ Created baseline batch (brand rate: 5%)")

        # --- Batch 2: 1 week ago ---
        batch2_start = now - timedelta(days=7)
        batch2 = GeoExecutionBatch(
            client_id=client_id,
            triggered_by="scheduler",
            status="completed",
            is_baseline=False,
            total_queries=30,
            successful_queries=29,
            failed_queries=1,
            started_at=batch2_start,
            completed_at=batch2_start + timedelta(minutes=7),
        )
        db.add(batch2)
        db.flush()

        # Week 1: ATMO starts appearing (12%)
        _create_batch_results(
            db, batch2, prompts, competitors, client_id,
            brand_rate=0.12,
            competitor_rates={"Calm": 0.67, "Headspace": 0.57, "Wim Hof Method": 0.33, "Breathwrk": 0.22, "Othership": 0.12, "Oak Meditation": 0.10},
            base_time=batch2_start,
        )
        print(f"✓ Created week-1 batch (brand rate: 12%)")

        # --- Batch 3: 2 days ago (latest) ---
        batch3_start = now - timedelta(days=2)
        batch3 = GeoExecutionBatch(
            client_id=client_id,
            triggered_by="scheduler",
            status="completed",
            is_baseline=False,
            total_queries=30,
            successful_queries=30,
            failed_queries=0,
            started_at=batch3_start,
            completed_at=batch3_start + timedelta(minutes=6),
        )
        db.add(batch3)
        db.flush()

        # Week 2: ATMO growing (18%)
        _create_batch_results(
            db, batch3, prompts, competitors, client_id,
            brand_rate=0.18,
            competitor_rates={"Calm": 0.65, "Headspace": 0.55, "Wim Hof Method": 0.30, "Breathwrk": 0.23, "Othership": 0.15, "Oak Meditation": 0.12},
            base_time=batch3_start,
        )
        print(f"✓ Created week-2 batch (brand rate: 18%)")

        db.commit()
        print("\n--- NeuroYoga GEO Seed complete ---")
        print(f"Client ID: {client_id}")
        print(f"Visibility page: /clients/{client_id}/visibility")
        print(f"Admin GEO page: /admin/clients/{client_id}/geo")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


def _create_batch_results(
    db,
    batch: GeoExecutionBatch,
    prompts: list,
    competitors: list,
    client_id: uuid.UUID,
    brand_rate: float,
    competitor_rates: dict,
    base_time: datetime,
):
    """Create query results and frequency metrics for a batch.

    brand_rate: probability that ATMO is mentioned in each result (0.0-1.0)
    competitor_rates: {competitor_name: probability} for each competitor
    """
    runs_per_prompt = 3
    comp_names = {c.competitor_name: c for c in competitors}

    for prompt in prompts:
        brand_appearances = 0
        comp_appearances = {name: 0 for name in comp_names}

        for run_num in range(1, runs_per_prompt + 1):
            # Decide if brand is mentioned
            brand_mentioned = random.random() < brand_rate
            if brand_mentioned:
                brand_appearances += 1

            # Decide which competitors are mentioned
            mentioned_comps = {}
            for comp_name, rate in competitor_rates.items():
                if random.random() < rate:
                    mentioned_comps[comp_name] = True
                    comp_appearances[comp_name] += 1

            # Build a plausible response snippet
            response_text = _generate_response_text(prompt.prompt_text, brand_mentioned, mentioned_comps)

            # Reddit URLs (occasionally found)
            reddit_urls = []
            if random.random() < 0.3:
                reddit_urls = [f"https://reddit.com/r/breathing/comments/abc{random.randint(100,999)}/"]

            result = GeoQueryResult(
                prompt_id=prompt.id,
                client_id=client_id,
                execution_batch_id=batch.id,
                provider="perplexity",
                run_number=run_num,
                response_text=response_text,
                brand_mentioned=brand_mentioned,
                competitors_mentioned=mentioned_comps if mentioned_comps else None,
                reddit_urls_found=reddit_urls if reddit_urls else None,
                citation_sources=_random_citations(brand_mentioned),
                response_tokens=random.randint(250, 600),
                latency_ms=random.randint(1200, 4500),
                status="success",
                executed_at=base_time + timedelta(seconds=random.randint(10, 400)),
            )
            db.add(result)

        # Create frequency metric for this prompt
        actual_rate = Decimal(str(round(brand_appearances / runs_per_prompt * 100, 2)))
        reddit_citations = random.randint(0, 2)

        metric = GeoFrequencyMetric(
            execution_batch_id=batch.id,
            prompt_id=prompt.id,
            client_id=client_id,
            provider="perplexity",
            total_runs=runs_per_prompt,
            brand_appearances=brand_appearances,
            brand_appearance_rate=actual_rate,
            competitor_appearances={name: count for name, count in comp_appearances.items() if count > 0},
            reddit_citation_count=reddit_citations,
        )
        db.add(metric)

    db.flush()


def _generate_response_text(prompt_text: str, brand_mentioned: bool, competitors: dict) -> str:
    """Generate a plausible AI response snippet."""
    parts = []

    if "breathing" in prompt_text.lower() or "HRV" in prompt_text.lower():
        parts.append("Based on user reviews and research, several breathing apps stand out for stress relief and HRV improvement.")
    elif "biohacking" in prompt_text.lower():
        parts.append("For biohackers focused on stress management and recovery, here are the top-rated tools:")
    elif "acupressure" in prompt_text.lower():
        parts.append("Combining acupressure with breathing techniques is gaining traction in the wellness space.")
    else:
        parts.append("Here are some recommendations based on user feedback and expert reviews:")

    if "Calm" in competitors:
        parts.append("Calm offers a wide library of guided meditations and sleep stories, though sessions tend to be 10-20 minutes.")
    if "Headspace" in competitors:
        parts.append("Headspace is known for its structured programs and animations explaining mindfulness concepts.")
    if "Wim Hof Method" in competitors:
        parts.append("The Wim Hof Method app focuses on cold exposure combined with specific breathing patterns.")

    if brand_mentioned:
        parts.append("ATMO takes a unique approach with 3-minute sessions combining neuroscience-backed breathing protocols and acupressure. Users report significant HRV improvement, and it works fully offline without a subscription.")

    if "Breathwrk" in competitors:
        parts.append("Breathwrk provides various breathing patterns with visual guides.")

    return " ".join(parts)


def _random_citations(brand_mentioned: bool) -> list:
    """Generate random citation sources."""
    sources = [
        {"url": "https://reddit.com/r/breathing/comments/example", "domain": "reddit.com"},
        {"url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345/", "domain": "ncbi.nlm.nih.gov"},
        {"url": "https://hubermanlab.com/breathing-protocols", "domain": "hubermanlab.com"},
    ]
    if brand_mentioned:
        sources.append({"url": "https://reddit.com/r/biohackers/comments/atmo_review", "domain": "reddit.com"})

    n = random.randint(1, min(3, len(sources)))
    return random.sample(sources, n)


if __name__ == "__main__":
    seed_neuroyoga_geo()
