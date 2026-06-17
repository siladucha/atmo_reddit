"""Seed GEO prompts and competitors for XM Cyber client.

Run: cd reddit_saas && python -m seed_geo_xmcyber
"""

import sys
sys.path.insert(0, ".")

from app.database import SessionLocal
from app.models.client import Client
from app.models.geo_prompt import GeoPrompt
from app.models.geo_competitor import GeoCompetitor


def seed_geo():
    db = SessionLocal()

    # Find XM Cyber client
    client = db.query(Client).filter(Client.client_name == "XM Cyber").first()
    if not client:
        print("ERROR: XM Cyber client not found!")
        return

    print(f"Found client: {client.client_name} (id: {client.id})")
    print(f"  brand_name: {client.brand_name}")
    print(f"  geo_monitoring_enabled: {client.geo_monitoring_enabled}")

    # Enable GEO monitoring if not already
    if not client.geo_monitoring_enabled:
        client.geo_monitoring_enabled = True
        db.commit()
        print("  -> Enabled geo_monitoring_enabled")

    # --- GEO Prompts ---
    # These are buyer-intent queries that enterprise security buyers ask AI assistants.
    # We check if XM Cyber appears in the AI response.

    prompts = [
        # Category: CTEM / Exposure Management (core positioning)
        {
            "prompt_text": "What are the best Continuous Threat Exposure Management (CTEM) platforms for enterprise?",
            "category": "ctem",
        },
        {
            "prompt_text": "Which tools help with attack path analysis and exposure management?",
            "category": "ctem",
        },
        {
            "prompt_text": "What is the difference between vulnerability management and exposure management?",
            "category": "ctem",
        },
        # Category: Attack Path / Attack Surface
        {
            "prompt_text": "What tools visualize attack paths across hybrid cloud environments?",
            "category": "attack_path",
        },
        {
            "prompt_text": "Best attack surface management tools for large enterprises 2025",
            "category": "attack_path",
        },
        {
            "prompt_text": "How do I prioritize which vulnerabilities to fix first based on exploitability?",
            "category": "attack_path",
        },
        # Category: Competitor comparison
        {
            "prompt_text": "XM Cyber vs Tenable vs Rapid7 — which is better for vulnerability prioritization?",
            "category": "vs_comparison",
        },
        {
            "prompt_text": "What are the alternatives to Pentera for continuous security validation?",
            "category": "vs_comparison",
        },
        {
            "prompt_text": "Compare breach and attack simulation tools: XM Cyber, SafeBreach, AttackIQ, Cymulate",
            "category": "vs_comparison",
        },
        # Category: Use case / problem-driven
        {
            "prompt_text": "How to reduce attack surface in a hybrid on-prem and cloud environment?",
            "category": "use_case",
        },
        {
            "prompt_text": "What tools help identify lateral movement paths in Active Directory?",
            "category": "use_case",
        },
        {
            "prompt_text": "Best tools for security posture validation without running attacks in production",
            "category": "use_case",
        },
    ]

    existing_prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client.id)
        .count()
    )
    if existing_prompts > 0:
        print(f"\n  WARNING: {existing_prompts} prompts already exist. Skipping prompt creation.")
    else:
        for p in prompts:
            geo_prompt = GeoPrompt(
                client_id=client.id,
                prompt_text=p["prompt_text"],
                category=p["category"],
                is_active=True,
            )
            db.add(geo_prompt)
        db.commit()
        print(f"\n  Created {len(prompts)} GEO prompts")

    # --- GEO Competitors ---
    # These are tracked to see if they appear in AI responses instead of/alongside XM Cyber.

    competitors = [
        {
            "competitor_name": "Tenable",
            "competitor_domain": "tenable.com",
            "aliases": ["Tenable.io", "Tenable One", "Nessus"],
        },
        {
            "competitor_name": "Rapid7",
            "competitor_domain": "rapid7.com",
            "aliases": ["InsightVM", "Nexpose"],
        },
        {
            "competitor_name": "Pentera",
            "competitor_domain": "pentera.io",
            "aliases": ["Pcysys"],
        },
        {
            "competitor_name": "SafeBreach",
            "competitor_domain": "safebreach.com",
            "aliases": [],
        },
        {
            "competitor_name": "AttackIQ",
            "competitor_domain": "attackiq.com",
            "aliases": [],
        },
        {
            "competitor_name": "Cymulate",
            "competitor_domain": "cymulate.com",
            "aliases": [],
        },
        {
            "competitor_name": "CrowdStrike",
            "competitor_domain": "crowdstrike.com",
            "aliases": ["Falcon", "Falcon Exposure Management"],
        },
        {
            "competitor_name": "Wiz",
            "competitor_domain": "wiz.io",
            "aliases": [],
        },
        {
            "competitor_name": "Qualys",
            "competitor_domain": "qualys.com",
            "aliases": ["VMDR"],
        },
        {
            "competitor_name": "Horizon3.ai",
            "competitor_domain": "horizon3.ai",
            "aliases": ["NodeZero"],
        },
    ]

    existing_competitors = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client.id)
        .count()
    )
    if existing_competitors > 0:
        print(f"  WARNING: {existing_competitors} competitors already exist. Skipping competitor creation.")
    else:
        for c in competitors:
            geo_comp = GeoCompetitor(
                client_id=client.id,
                competitor_name=c["competitor_name"],
                competitor_domain=c["competitor_domain"],
                aliases=c["aliases"],
                is_active=True,
            )
            db.add(geo_comp)
        db.commit()
        print(f"  Created {len(competitors)} GEO competitors")

    # Summary
    print("\n--- GEO Setup Summary for XM Cyber ---")
    print(f"  Prompts: {db.query(GeoPrompt).filter(GeoPrompt.client_id == client.id, GeoPrompt.is_active == True).count()} active")
    print(f"  Competitors: {db.query(GeoCompetitor).filter(GeoCompetitor.client_id == client.id, GeoCompetitor.is_active == True).count()} active")
    print(f"  GEO monitoring enabled: {client.geo_monitoring_enabled}")
    print("\n  Now press 'Run' on /admin/clients/{client_id}/geo to execute a batch.")
    print("  NOTE: Requires 'geo_perplexity_api_key' in System Settings.")

    db.close()


if __name__ == "__main__":
    seed_geo()
