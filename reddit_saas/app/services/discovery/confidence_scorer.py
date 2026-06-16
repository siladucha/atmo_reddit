"""Confidence Scorer — rule-based hypothesis confidence calculation.

Pure Python, no LLM calls, no external API calls. Applies deterministic scoring
rules based on Reddit signal strength to calculate hypothesis confidence.

Scoring rules (from Requirements 4 & 5):
- Base score: 50 (neutral, before research)
- Strong signal: ≥20 posts in 30d AND ≥10 avg engagement → +10 per strong subreddit, capped at +30
- Weak signal: <5 posts in 30d OR <3 avg engagement → -10 per weak area, capped at -30
- No signal: when BOTH primary AND broad terms fail → force score to 15, attach no_signal assessment

No-Signal Classification (Requirement 5):
- "search_too_narrow": broader related terms return 10+ relevant posts but hypothesis-specific <5
  - Suggestion: up to 3 adjacent Reddit topics or rephrased angles
- "topic_absent": BOTH hypothesis-specific AND broader terms return <5 relevant posts
  - Suggestion: up to 3 alternative platforms outside Reddit

This service does NOT modify the database — it returns a result dict.
The caller is responsible for updating the hypothesis record.
"""

from __future__ import annotations

from app.logging_config import get_logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.discovery_hypothesis import DiscoveryHypothesis

logger = get_logger(__name__)

# --- Constants ---
BASE_SCORE = 50
STRONG_POST_THRESHOLD = 20
STRONG_ENGAGEMENT_THRESHOLD = 10
WEAK_POST_THRESHOLD = 5
WEAK_ENGAGEMENT_THRESHOLD = 3
STRONG_BONUS_PER_SUB = 10
STRONG_BONUS_CAP = 30
WEAK_PENALTY_PER_AREA = 10
WEAK_PENALTY_CAP = 30
NO_SIGNAL_SCORE = 15
BROADER_SEARCH_THRESHOLD = 10


def score_hypothesis(hypothesis: DiscoveryHypothesis, signals: dict) -> dict:
    """Pure Python confidence scoring — NO LLM calls.

    Args:
        hypothesis: The hypothesis record being scored.
        signals: The reddit_signals dict from Reddit research, with structure:
            {
                "subreddits": [{"name": "r/...", "subscribers": N, "posts_30d": N,
                                "avg_engagement": N, "relevance_score": N}],
                "total_posts_found": N,
                "avg_engagement_overall": N,
                "broader_search": {"posts_found": N, "terms_used": [...]}  # optional
            }

    Returns:
        Dict with:
            - confidence_score: int (0-100)
            - confidence_delta: int (change from initial 50)
            - confidence_reasoning: str (explanation of calculation)
            - no_signal: dict | None (if applicable: {cause, explanation, suggestions})
    """
    subreddits = signals.get("subreddits", [])
    total_posts = signals.get("total_posts_found", 0)
    avg_engagement_overall = signals.get("avg_engagement_overall", 0.0)
    broader_search = signals.get("broader_search")

    # --- No-Signal Detection ---
    # Check if BOTH primary and broad terms fail
    primary_has_signal = total_posts >= WEAK_POST_THRESHOLD
    broader_has_signal = (
        broader_search is not None
        and broader_search.get("posts_found", 0) >= BROADER_SEARCH_THRESHOLD
    )

    if not primary_has_signal:
        no_signal_result = _classify_no_signal(
            hypothesis=hypothesis,
            total_posts=total_posts,
            broader_search=broader_search,
            primary_has_signal=primary_has_signal,
            broader_has_signal=broader_has_signal,
        )
        if no_signal_result is not None:
            return {
                "confidence_score": NO_SIGNAL_SCORE,
                "confidence_delta": NO_SIGNAL_SCORE - BASE_SCORE,
                "confidence_reasoning": (
                    f"No signal detected: {no_signal_result['explanation']}"
                ),
                "no_signal": no_signal_result,
            }

    # --- Signal-Based Scoring ---
    adjustment = 0
    reasoning_parts: list[str] = []

    # Count strong subreddits (≥20 posts in 30d AND ≥10 avg engagement)
    strong_subs = [
        s for s in subreddits
        if s.get("posts_30d", 0) >= STRONG_POST_THRESHOLD
        and s.get("avg_engagement", 0) >= STRONG_ENGAGEMENT_THRESHOLD
    ]

    # Count weak subreddits (<5 posts in 30d OR <3 avg engagement)
    weak_subs = [
        s for s in subreddits
        if s.get("posts_30d", 0) < WEAK_POST_THRESHOLD
        or s.get("avg_engagement", 0) < WEAK_ENGAGEMENT_THRESHOLD
    ]

    # Strong signal bonus: +10 per strong subreddit, capped at +30
    if strong_subs:
        bonus = min(len(strong_subs) * STRONG_BONUS_PER_SUB, STRONG_BONUS_CAP)
        adjustment += bonus
        sub_names = ", ".join(s.get("name", "?") for s in strong_subs[:3])
        reasoning_parts.append(
            f"+{bonus} from {len(strong_subs)} strong subreddit(s) "
            f"({sub_names}) with ≥{STRONG_POST_THRESHOLD} posts/30d "
            f"and ≥{STRONG_ENGAGEMENT_THRESHOLD} avg engagement"
        )

    # Weak signal penalty: -10 per weak area, capped at -30
    if weak_subs:
        penalty = min(len(weak_subs) * WEAK_PENALTY_PER_AREA, WEAK_PENALTY_CAP)
        adjustment -= penalty
        sub_names = ", ".join(s.get("name", "?") for s in weak_subs[:3])
        reasoning_parts.append(
            f"-{penalty} from {len(weak_subs)} weak area(s) "
            f"({sub_names}) with <{WEAK_POST_THRESHOLD} posts/30d "
            f"or <{WEAK_ENGAGEMENT_THRESHOLD} avg engagement"
        )

    # Calculate final score, clamped to [0, 100]
    new_score = max(0, min(100, BASE_SCORE + adjustment))
    confidence_delta = new_score - BASE_SCORE

    # Build reasoning text
    if reasoning_parts:
        reasoning = (
            f"Base: {BASE_SCORE}. " + "; ".join(reasoning_parts) + f". Final: {new_score}."
        )
    else:
        reasoning = (
            f"Base: {BASE_SCORE}. No strong or weak signals detected "
            f"({len(subreddits)} subreddits found with moderate activity). "
            f"Final: {new_score}."
        )

    return {
        "confidence_score": new_score,
        "confidence_delta": confidence_delta,
        "confidence_reasoning": reasoning,
        "no_signal": None,
    }


def _classify_no_signal(
    hypothesis: DiscoveryHypothesis,
    total_posts: int,
    broader_search: dict | None,
    primary_has_signal: bool,
    broader_has_signal: bool,
) -> dict | None:
    """Classify the no-signal cause and generate suggestions.

    Returns:
        A no_signal dict or None if no-signal classification doesn't apply.
    """
    if primary_has_signal:
        # Primary terms found enough posts — not a no-signal scenario
        return None

    if broader_has_signal:
        # "search_too_narrow": broader terms return 10+ but hypothesis-specific <5
        broader_terms = broader_search.get("terms_used", []) if broader_search else []
        suggestions = _generate_narrow_suggestions(hypothesis, broader_terms)

        return {
            "cause": "search_too_narrow",
            "explanation": (
                f"Broader related search terms returned "
                f"{broader_search.get('posts_found', 0)} relevant posts, "
                f"but hypothesis-specific terms returned only {total_posts}. "
                f"The topic likely exists on Reddit under different terminology."
            ),
            "suggestions": suggestions,
        }
    else:
        # "topic_absent": BOTH hypothesis-specific AND broader terms return <5
        suggestions = _generate_absent_suggestions(hypothesis)

        broader_posts = (
            broader_search.get("posts_found", 0) if broader_search else 0
        )
        return {
            "cause": "topic_absent",
            "explanation": (
                f"Both hypothesis-specific terms ({total_posts} posts) "
                f"and broader related terms ({broader_posts} posts) "
                f"returned fewer than {WEAK_POST_THRESHOLD} relevant posts "
                f"across all searched subreddits. "
                f"This topic has minimal Reddit presence."
            ),
            "suggestions": suggestions,
        }


def _generate_narrow_suggestions(
    hypothesis: DiscoveryHypothesis, broader_terms: list[str]
) -> list[str]:
    """Generate up to 3 adjacent Reddit topics or rephrased angles.

    Uses broader search terms that DID return results to suggest
    adjacent angles the operator could explore.
    """
    suggestions: list[str] = []

    # Use the broader terms that worked as suggestion basis
    if broader_terms:
        for term in broader_terms[:3]:
            suggestions.append(
                f"Try researching with broader term: '{term}'"
            )

    # If we have fewer than 3 suggestions, add generic reframe suggestions
    category = hypothesis.category if hypothesis else "general"
    reframe_suggestions = _get_reframe_suggestions(category)
    while len(suggestions) < 3 and reframe_suggestions:
        suggestions.append(reframe_suggestions.pop(0))

    return suggestions[:3]


def _generate_absent_suggestions(hypothesis: DiscoveryHypothesis) -> list[str]:
    """Generate up to 3 alternative platforms outside Reddit.

    When a topic is truly absent from Reddit, suggest where else
    the conversation might be happening.
    """
    category = hypothesis.category if hypothesis else "general"

    # Map hypothesis categories to likely alternative platforms
    platform_suggestions = {
        "clients": [
            "LinkedIn Groups focused on the target industry",
            "Quora spaces discussing the problem domain",
            "Industry-specific forums (e.g., Stack Exchange, niche communities)",
        ],
        "partners": [
            "LinkedIn professional groups in the target space",
            "Industry conference communities and Slack channels",
            "Partnership marketplaces (e.g., PartnerStack, Crossbeam communities)",
        ],
        "feedback": [
            "G2/Capterra review communities",
            "Product Hunt discussions",
            "Industry-specific Slack/Discord communities",
        ],
        "recognition": [
            "LinkedIn company discussions and mentions",
            "Twitter/X industry conversations",
            "Industry publication comment sections and forums",
        ],
        "hiring": [
            "LinkedIn talent communities",
            "Blind (anonymous workplace discussions)",
            "Glassdoor and industry-specific job boards",
        ],
        "market_research": [
            "Quora spaces for the target industry",
            "LinkedIn industry groups and thought leadership",
            "Industry analyst communities and Discord servers",
        ],
    }

    return platform_suggestions.get(category, [
        "LinkedIn Groups for the relevant industry",
        "Quora spaces discussing related topics",
        "Industry-specific forums and Discord communities",
    ])[:3]


def _get_reframe_suggestions(category: str) -> list[str]:
    """Get category-specific reframe suggestions for narrow searches."""
    reframes = {
        "clients": [
            "Search for the problem the product solves rather than the product name",
            "Try related subreddits focused on the target audience's daily challenges",
            "Look for comparison/recommendation request threads",
        ],
        "partners": [
            "Search for communities where potential partners share workflows",
            "Try integration-focused subreddits (e.g., r/SaaS, r/startups)",
            "Look for 'tech stack' discussion threads",
        ],
        "feedback": [
            "Search for the problem category rather than specific product names",
            "Try subreddits where users discuss alternatives and complaints",
            "Look for 'what do you use for...' type threads",
        ],
        "recognition": [
            "Search for industry-specific discussion subreddits",
            "Try competitor brand names as search terms",
            "Look for 'best of' or recommendation megathreads",
        ],
        "hiring": [
            "Search for role-specific career subreddits",
            "Try industry + 'career' or 'job' as search terms",
            "Look for salary/compensation discussion threads",
        ],
        "market_research": [
            "Search for the broader industry trend, not just the niche",
            "Try adjacent problem spaces that overlap with the target market",
            "Look for 'state of' or annual discussion threads",
        ],
    }
    return reframes.get(category, [
        "Try broader terminology related to the hypothesis",
        "Search for the underlying problem rather than the specific solution",
        "Look for adjacent communities discussing related topics",
    ])
