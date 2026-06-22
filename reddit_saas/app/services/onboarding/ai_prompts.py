"""AI Prompts for Onboarding — profile synthesis, positioning extraction, ICP, keywords, subreddits.

All use Gemini Flash (cheap, fast) via call_llm_json().
"""

from app.logging_config import get_logger
from app.services.ai import call_llm_json, log_ai_usage

logger = get_logger(__name__)

ONBOARDING_MODEL = "gemini/gemini-2.5-flash"


# --- Step 1: Profile Synthesis ---

PROFILE_SYNTHESIS_PROMPT = """You are a B2B business analyst. Given scraped website content, extract a structured company profile.

RULES:
- Be concise and factual. No marketing fluff.
- If information is not available in the text, return null for that field.
- company_size_estimate: infer from language, team page references, or "enterprise" vs "startup" signals.
- industry: use standard industry categories (Cybersecurity, DevOps, Marketing Tech, etc.)
- customer_pain: describe the problem from the customer's perspective (frustration, inefficiency, risk)
- unique_advantage: what this product does that competitors likely cannot — infer from positioning
- competitors_inferred: list competitor names if mentioned; otherwise infer from the market category

OUTPUT (strict JSON):
{
  "company_name": "string",
  "product_description": "1-2 sentence description of what the product does",
  "value_proposition": "1 sentence: why customers choose this over alternatives",
  "key_differentiators": ["string", "string", "string"],
  "industry": "string",
  "company_size_estimate": "startup|smb|mid-market|enterprise|unknown",
  "customer_pain": "2-3 sentences: what the customer's life looks like WITHOUT this product (pain, frustration, risk)",
  "unique_advantage": "2-3 sentences: what makes this product irreplaceable vs alternatives",
  "competitors_inferred": ["string", "string"]
}"""


def synthesize_profile(scraped_data: dict, db=None, client_id: str | None = None) -> dict:
    """Convert scraped website data into structured company profile.

    Args:
        scraped_data: Output from website_scraper (pages dict, title, meta_description)
        db: Optional DB session for cost logging
        client_id: Optional client ID for cost tracking

    Returns:
        Dict with company_name, product_description, value_proposition,
        key_differentiators, industry, company_size_estimate.
        On failure: returns dict with "error" key.
    """
    # Build context from scraped pages
    parts = []
    if scraped_data.get("title"):
        parts.append(f"Page title: {scraped_data['title']}")
    if scraped_data.get("meta_description"):
        parts.append(f"Meta description: {scraped_data['meta_description']}")
    for page_type, text in scraped_data.get("pages", {}).items():
        parts.append(f"\n--- {page_type.upper()} PAGE ---\n{text[:3000]}")

    if not parts:
        return {"error": "No content to analyze"}

    content = "\n".join(parts)

    messages = [
        {"role": "system", "content": PROFILE_SYNTHESIS_PROMPT},
        {"role": "user", "content": f"Website content:\n\n{content}"},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.2,
            max_tokens=512,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_profile_synthesis", result)
        return result["data"]
    except Exception as e:
        logger.error("Profile synthesis failed: %s", e)
        return {"error": str(e)}


# --- Step 2: Positioning Extraction ---

POSITIONING_PROMPT = """You are a positioning strategist. Extract structured positioning data from the client's answers about their product and market.

INPUT: Three answers from the client about their product, competitors, and differentiation.

OUTPUT (strict JSON):
{
  "company_worldview": "2-3 sentences: the client's core belief about their industry/market that drives their product decisions",
  "company_problem": "2-3 sentences: the specific problem their customers face, in the customer's language",
  "competitive_landscape": "2-3 sentences: how this product differs from named competitors and the general market",
  "competitor_names": ["string", "string"]
}

RULES:
- Use the client's own language where possible (preserve their phrasing)
- company_worldview should feel like a manifesto statement, not a product description
- company_problem should use pain language (frustration, inefficiency, risk)
- competitive_landscape should be specific about named competitors, not generic"""


def extract_positioning(answers: dict, db=None, client_id: str | None = None) -> dict:
    """Extract positioning data from client's free-text answers.

    Args:
        answers: {"before_product": "...", "unique_value": "...", "competitors": "..."}
        db: Optional DB session for cost logging
        client_id: Optional client ID for cost tracking

    Returns:
        Dict with company_worldview, company_problem, competitive_landscape, competitor_names.
    """
    user_content = f"""Client's answers:

1. What does your best customer say their life was like before using you?
{answers.get('before_product', '(not answered)')}

2. What does your product do that competitors cannot?
{answers.get('unique_value', '(not answered)')}

3. Name your 2-3 main competitors:
{answers.get('competitors', '(not answered)')}"""

    messages = [
        {"role": "system", "content": POSITIONING_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.3,
            max_tokens=512,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_positioning", result)
        return result["data"]
    except Exception as e:
        logger.error("Positioning extraction failed: %s", e)
        return {"error": str(e)}


# --- Step 3: ICP Synthesis ---

ICP_SYNTHESIS_PROMPT = """You are a B2B/B2C marketing strategist. Synthesize the ICP data into a concise, actionable profile description.

OUTPUT: A 3-5 sentence prose description of the Ideal Customer Profile. Include: who they are, their daily frustration, what they search for online, and what signals indicate they're in buying mode.

Write in second person ("Your ideal customer is..."). Be specific, not generic."""


def synthesize_icp(form_data: dict, business_type: str, db=None, client_id: str | None = None) -> str:
    """Convert structured ICP form data into prose description.

    Args:
        form_data: {"job_titles": "...", "seniority": "...", "frustration": "...", "search_query": "...", "adjacent_icp": "..."}
        business_type: "b2b" or "b2c"
        db: Optional DB session for cost logging
        client_id: Optional client ID for cost tracking

    Returns:
        Prose string for icp_profiles field.
    """
    if business_type == "b2b":
        user_content = f"""Business type: B2B

Primary ICP:
- Job titles: {form_data.get('job_titles', '')}
- Seniority: {form_data.get('seniority', '')}
- Day-to-day frustration: {form_data.get('frustration', '')}
- What they search before finding us: {form_data.get('search_query', '')}

Adjacent ICP (optional):
{form_data.get('adjacent_icp', '(none)')}"""
    else:
        user_content = f"""Business type: B2C

Primary ICP:
- Demographics: {form_data.get('demographics', '')}
- Interests: {form_data.get('interests', '')}
- Frustration: {form_data.get('frustration', '')}
- What they search: {form_data.get('search_query', '')}"""

    messages = [
        {"role": "system", "content": ICP_SYNTHESIS_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        from app.services.ai import call_llm
        result = call_llm(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.4,
            max_tokens=300,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_icp", result)
        return result["content"].strip()
    except Exception as e:
        logger.error("ICP synthesis failed: %s", e)
        # Fallback: return raw form data as text
        return f"Job titles: {form_data.get('job_titles', '')}. Frustration: {form_data.get('frustration', '')}. Searches for: {form_data.get('search_query', '')}"


# --- Step 5: Keyword Suggestion ---

KEYWORD_SUGGESTION_PROMPT = """You are a Reddit keyword strategist. Given a company profile, ICP, and competitors, suggest keywords that people use when discussing these topics on Reddit.

RULES:
- Keywords should be phrases people actually type in Reddit search or post titles
- Include: product category terms, pain language, competitor names, technical jargon, use-case phrases
- Categorize by priority: high (directly buying-signal), medium (relevant professional discussion), low (adjacent/awareness)
- 8-12 high, 10-15 medium, 8-12 low
- No single-word keywords (too broad). Minimum 2 words each.

OUTPUT (strict JSON):
{
  "high": ["phrase 1", "phrase 2"],
  "medium": ["phrase 1", "phrase 2"],
  "low": ["phrase 1", "phrase 2"]
}"""


def suggest_keywords(
    company_profile: str,
    icp_profiles: str,
    competitors: list[str],
    industry: str = "",
    db=None,
    client_id: str | None = None,
) -> dict:
    """AI-powered keyword suggestion from client profile data.

    Returns:
        Dict with high/medium/low keyword tiers.
    """
    user_content = f"""Company: {company_profile[:1000]}

ICP: {icp_profiles[:500]}

Competitors: {', '.join(competitors) if competitors else 'not specified'}

Industry: {industry or 'not specified'}"""

    messages = [
        {"role": "system", "content": KEYWORD_SUGGESTION_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.5,
            max_tokens=1024,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_keywords", result)
        return result["data"]
    except Exception as e:
        logger.error("Keyword suggestion failed: %s", e)
        return {"high": [], "medium": [], "low": [], "error": str(e)}


# --- Step 5: Subreddit Suggestion ---

SUBREDDIT_SUGGESTION_PROMPT = """You are a Reddit community analyst. Given keywords, industry, and competitors, suggest the best subreddits for brand presence building.

RULES:
- Suggest 8-15 subreddits total
- Include a mix: professional (where ICP hangs out), hobby-adjacent (for Phase 1 warming), competitor-frequented
- For each subreddit, explain WHY it fits this specific company
- audience_fit: how closely the subreddit's audience matches the ICP
- Be specific — real subreddit names that exist on Reddit. No made-up names.
- Prefer subreddits with 10k+ subscribers and active daily posts

OUTPUT (strict JSON):
{
  "subreddits": [
    {
      "name": "subreddit_name_without_r_prefix",
      "type": "professional|hobby|adjacent",
      "rationale": "1-2 sentences explaining why this subreddit matters for this company",
      "audience_fit": "high|medium|low",
      "estimated_subscribers": 50000
    }
  ]
}"""


def suggest_subreddits(
    keywords: dict,
    industry: str,
    competitors: list[str],
    company_profile: str = "",
    db=None,
    client_id: str | None = None,
) -> list[dict]:
    """AI-powered subreddit suggestion.

    Returns:
        List of subreddit dicts with name, type, rationale, audience_fit.
    """
    # Flatten keywords for context
    all_keywords = []
    for tier, kws in keywords.items():
        if isinstance(kws, list):
            all_keywords.extend(kws[:10])  # Max 10 per tier to keep prompt short

    user_content = f"""Industry: {industry or 'not specified'}

Key topics: {', '.join(all_keywords[:20])}

Competitors: {', '.join(competitors) if competitors else 'not specified'}

Company summary: {company_profile[:500]}"""

    messages = [
        {"role": "system", "content": SUBREDDIT_SUGGESTION_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.5,
            max_tokens=1500,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_subreddits", result)

        data = result["data"]
        return data.get("subreddits", [])
    except Exception as e:
        logger.error("Subreddit suggestion failed: %s", e)
        return []


# --- Step 2: Auto-fill from company profile ---

AUTOFILL_STEP2_PROMPT = """You are a B2B positioning analyst. Given a company profile and industry, infer:
1. What pain the customer experiences WITHOUT this product (frustration, risk, inefficiency)
2. What makes this product's approach unique vs alternatives
3. Who the likely competitors are

OUTPUT (strict JSON):
{
  "customer_pain": "2-3 sentences in customer voice: their life BEFORE this product. Use pain language.",
  "unique_advantage": "2-3 sentences: what this product does that competitors cannot. Be specific.",
  "competitors": "Comma-separated list of 2-4 likely competitor names or categories"
}

RULES:
- Infer from the company description. Don't make up fake specifics.
- customer_pain should sound like a real person describing their frustration
- If you can't infer competitors, name the market category (e.g. "traditional consulting firms, freelance CTOs")"""


def autofill_step2(company_profile: str, industry: str, db=None, client_id: str | None = None) -> dict:
    """Auto-fill Step 2 fields from company profile using AI."""
    messages = [
        {"role": "system", "content": AUTOFILL_STEP2_PROMPT},
        {"role": "user", "content": f"Company profile: {company_profile[:2000]}\nIndustry: {industry}"},
    ]
    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.3,
            max_tokens=512,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_autofill_step2", result)
        return result["data"]
    except Exception as e:
        logger.error("Step 2 autofill failed: %s", e)
        return {"error": str(e)}


# --- Step 3: Auto-fill ICP from profile + problem ---

AUTOFILL_STEP3_PROMPT = """You are a B2B buyer persona analyst. Given a company profile, their customer's pain, and competitors, infer the Ideal Customer Profile.

OUTPUT (strict JSON):
{
  "business_type": "b2b",
  "job_titles": "2-4 job titles separated by comma (e.g. CTO, VP Engineering, Technical Co-founder)",
  "seniority": "c-level|director|manager|ic",
  "frustration": "2-3 sentences: their daily frustration that leads them to seek this solution",
  "search_query": "3-5 phrases they would Google or search on Reddit, comma-separated",
  "adjacent_icp": "1 sentence: a secondary buyer who influences the decision (optional, can be empty)"
}

RULES:
- Infer from available context. Be specific to the industry.
- job_titles should be real titles used in this industry
- search_query should be natural language phrases (not keywords)
- frustration should sound like a real person venting"""


def autofill_step3(
    company_profile: str,
    company_problem: str,
    competitive_landscape: str,
    industry: str,
    db=None,
    client_id: str | None = None,
) -> dict:
    """Auto-fill Step 3 ICP fields from available client data."""
    context = f"""Company: {company_profile[:1500]}
Customer pain: {company_problem[:500]}
Competitors: {competitive_landscape[:300]}
Industry: {industry}"""

    messages = [
        {"role": "system", "content": AUTOFILL_STEP3_PROMPT},
        {"role": "user", "content": context},
    ]
    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.3,
            max_tokens=512,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_autofill_step3", result)
        return result["data"]
    except Exception as e:
        logger.error("Step 3 autofill failed: %s", e)
        return {"error": str(e)}


# --- Step 4: Auto-fill Voice & Guardrails ---

AUTOFILL_STEP4_PROMPT = """You are a brand strategist. Given a company profile, industry, and competitors, suggest brand voice guardrails.

OUTPUT (strict JSON):
{
  "never_associated": "2-3 topics/sentiments the brand should NEVER be linked to on Reddit",
  "legal_limits": "1-2 claims the company likely cannot make given the industry",
  "admired_style": "1 brand/publication whose communication style fits this company",
  "brand_voice": "2-3 sentences describing the ideal tone: formality, technical depth, personality"
}

RULES:
- Be specific to the industry and company type
- never_associated should include actual harmful associations for this industry
- brand_voice should be actionable (not generic like 'professional and friendly')"""


def autofill_step4(
    company_profile: str,
    industry: str,
    competitive_landscape: str,
    db=None,
    client_id: str | None = None,
) -> dict:
    """Auto-fill Step 4 voice & guardrail fields from company context."""
    context = f"""Company: {company_profile[:1500]}
Industry: {industry}
Competitors: {competitive_landscape[:500]}"""

    messages = [
        {"role": "system", "content": AUTOFILL_STEP4_PROMPT},
        {"role": "user", "content": context},
    ]
    try:
        result = call_llm_json(
            messages=messages,
            model=ONBOARDING_MODEL,
            temperature=0.4,
            max_tokens=512,
        )
        if db and client_id:
            log_ai_usage(db, client_id, "onboarding_autofill_step4", result)
        return result["data"]
    except Exception as e:
        logger.error("Step 4 autofill failed: %s", e)
        return {"error": str(e)}
