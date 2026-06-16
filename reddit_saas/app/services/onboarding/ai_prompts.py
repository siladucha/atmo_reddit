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

OUTPUT (strict JSON):
{
  "company_name": "string",
  "product_description": "1-2 sentence description of what the product does",
  "value_proposition": "1 sentence: why customers choose this over alternatives",
  "key_differentiators": ["string", "string", "string"],
  "industry": "string",
  "company_size_estimate": "startup|smb|mid-market|enterprise|unknown"
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
