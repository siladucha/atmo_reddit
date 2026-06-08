"""Reddit Researcher — searches Reddit for evidence supporting/contradicting hypotheses.

Uses PRAW to search subreddits, collect engagement metrics, and evaluate
topic relevance. Lightweight queries (no thread persistence) designed for
Discovery signal collection.

This service is SYNCHRONOUS (PRAW is synchronous). Called from Celery tasks.
Rate limiting is handled by the existing reddit.py infrastructure via
get_reddit_client() which enforces the global Redis sliding window limiter.

The researcher does NOT use scrape_subreddit(). Instead, it uses lightweight
PRAW queries (reddit.subreddits.search(), subreddit.hot()) for signal
collection without persisting raw thread data.
"""

import re
import time
from datetime import datetime, timezone

from app.logging_config import get_logger
from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.schemas.discovery import NoSignalAssessment, RedditSignalOutput, SubredditSignal
from app.services.reddit import get_reddit_client

logger = get_logger(__name__)

# Max time per hypothesis research (seconds)
PER_HYPOTHESIS_TIMEOUT = 20

# Stop words excluded from hypothesis statement parsing
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "because", "about",
    "that", "this", "these", "those", "it", "its", "and", "but", "or",
    "if", "while", "although", "their", "they", "them", "we", "us", "our",
    "you", "your", "he", "she", "him", "her", "his", "who", "which",
    "what", "reddit", "subreddit", "community", "communities", "users",
    "people", "likely", "potential", "significant", "active", "relevant",
})


def research_hypothesis(
    hypothesis: DiscoveryHypothesis,
    entities: list[DiscoveryEntity],
) -> RedditSignalOutput:
    """Research Reddit for evidence supporting/contradicting a hypothesis.

    Uses lightweight PRAW queries (subreddit search, hot posts) to collect
    signals without persisting raw thread data.

    This function is SYNCHRONOUS because PRAW is synchronous. It is designed
    to be called from a Celery task.

    Args:
        hypothesis: The hypothesis to research.
        entities: Session entities for additional search terms.

    Returns:
        Validated RedditSignalOutput with subreddit data, post volumes,
        engagement metrics, and optional no-signal assessment.
    """
    start_time = time.time()

    # Step 1: Extract search terms from hypothesis statement + entity names
    search_terms = _extract_search_terms(hypothesis, entities)
    if not search_terms:
        logger.warning(
            "DISCOVERY_RESEARCH | hypothesis_id=%s | action=no_search_terms",
            hypothesis.id,
        )
        return RedditSignalOutput(
            subreddits=[],
            total_posts_found=0,
            avg_engagement=0.0,
            no_signal=NoSignalAssessment(
                cause="topic_absent",
                explanation="Could not derive search terms from hypothesis statement or entities.",
                suggestions=_suggest_alternative_platforms(entities),
            ),
        )

    logger.info(
        "DISCOVERY_RESEARCH | hypothesis_id=%s | action=start | search_terms=%s",
        hypothesis.id, search_terms[:5],
    )

    # Step 2: Get Reddit client (rate-limited via global limiter)
    try:
        reddit = get_reddit_client(caller="discovery_research")
    except Exception as e:
        logger.error(
            "DISCOVERY_RESEARCH | hypothesis_id=%s | action=client_error | error=%s",
            hypothesis.id, str(e),
        )
        return RedditSignalOutput(
            subreddits=[],
            total_posts_found=0,
            avg_engagement=0.0,
            no_signal=NoSignalAssessment(
                cause="topic_absent",
                explanation=f"Reddit API unavailable: {str(e)[:200]}",
                suggestions=["Retry later when Reddit API is accessible."],
            ),
        )

    # Step 3: Search for relevant subreddits
    subreddit_signals: list[SubredditSignal] = []
    total_posts_found = 0

    try:
        # Primary query from top search terms
        primary_query = " ".join(search_terms[:3])
        found_subs = []

        for sub in reddit.subreddits.search(primary_query, limit=10):
            if time.time() - start_time > PER_HYPOTHESIS_TIMEOUT:
                logger.info(
                    "DISCOVERY_RESEARCH | hypothesis_id=%s | action=timeout_subreddit_search",
                    hypothesis.id,
                )
                break
            found_subs.append(sub)

        # Step 4: For each subreddit, collect signals
        for sub in found_subs:
            if time.time() - start_time > PER_HYPOTHESIS_TIMEOUT:
                break

            try:
                signal = _analyze_subreddit(sub, search_terms)
                if signal:
                    subreddit_signals.append(signal)
                    total_posts_found += signal.posts_30d
            except Exception as e:
                logger.debug(
                    "DISCOVERY_RESEARCH | hypothesis_id=%s | subreddit=r/%s | error=%s",
                    hypothesis.id, getattr(sub, "display_name", "?"), str(e),
                )
                continue

    except Exception as e:
        logger.warning(
            "DISCOVERY_RESEARCH | hypothesis_id=%s | action=search_failed | error=%s",
            hypothesis.id, str(e),
        )
        # If we got some signals before failure, continue with what we have
        if not subreddit_signals:
            return RedditSignalOutput(
                subreddits=[],
                total_posts_found=0,
                avg_engagement=0.0,
                no_signal=NoSignalAssessment(
                    cause="topic_absent",
                    explanation=f"Reddit search failed: {str(e)[:200]}",
                    suggestions=["Retry research — transient Reddit API error."],
                ),
            )

    # Step 5: Calculate overall average engagement
    avg_engagement = 0.0
    if subreddit_signals:
        total_eng = sum(s.avg_engagement for s in subreddit_signals)
        avg_engagement = round(total_eng / len(subreddit_signals), 1)

    # Step 6: No-signal detection and broader search
    no_signal = None
    if total_posts_found < 5:
        no_signal = _assess_no_signal(
            reddit, entities, search_terms, total_posts_found, start_time
        )

    # Sort by relevance score descending
    sorted_signals = sorted(
        subreddit_signals, key=lambda s: s.relevance_score, reverse=True
    )

    logger.info(
        "DISCOVERY_RESEARCH | hypothesis_id=%s | action=complete | "
        "subreddits_found=%d | total_posts=%d | avg_engagement=%.1f | "
        "no_signal=%s | duration_ms=%d",
        hypothesis.id, len(sorted_signals), total_posts_found, avg_engagement,
        no_signal.cause if no_signal else "none",
        int((time.time() - start_time) * 1000),
    )

    return RedditSignalOutput(
        subreddits=sorted_signals,
        total_posts_found=total_posts_found,
        avg_engagement=avg_engagement,
        no_signal=no_signal,
    )


def _extract_search_terms(
    hypothesis: DiscoveryHypothesis,
    entities: list[DiscoveryEntity],
) -> list[str]:
    """Extract search terms from hypothesis statement + entity names.

    Strategy:
    1. Use pre-computed search_terms from provenance (if available from LLM)
    2. Parse hypothesis statement for significant keywords (3+ chars, no stop words)
    3. Add entity names as additional terms
    4. Deduplicate, limit to 7 terms max
    """
    terms: list[str] = []

    # Source 1: From provenance (LLM-generated search terms)
    provenance = hypothesis.provenance or {}
    if "search_terms" in provenance and provenance["search_terms"]:
        terms.extend(provenance["search_terms"])

    # Source 2: Parse hypothesis statement for meaningful keywords
    statement = hypothesis.statement or ""
    statement_keywords = _parse_statement_keywords(statement)
    terms.extend(statement_keywords)

    # Source 3: Entity names from triggering entities in provenance
    triggering = provenance.get("triggering_entities", [])
    for ent in triggering:
        if isinstance(ent, dict) and ent.get("name"):
            terms.append(ent["name"])

    # Source 4: Fallback — use session entity names directly
    if len(terms) < 3:
        for e in entities[:5]:
            terms.append(e.name)

    # Deduplicate while preserving priority order
    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        t_clean = t.strip()
        t_lower = t_clean.lower()
        if t_lower and t_lower not in seen and len(t_clean) >= 2:
            seen.add(t_lower)
            unique.append(t_clean)

    return unique[:7]


def _parse_statement_keywords(statement: str) -> list[str]:
    """Parse hypothesis statement text into meaningful keyword list.

    Extracts multi-word phrases and significant single words,
    filtering stop words and short tokens.
    """
    if not statement:
        return []

    # Extract quoted phrases first (e.g., "machine learning")
    quoted = re.findall(r'"([^"]+)"', statement)
    keywords = list(quoted)

    # Remove quoted sections and tokenize remaining
    cleaned = re.sub(r'"[^"]*"', "", statement)
    # Split on non-alphanumeric (keeping hyphens within words)
    words = re.findall(r"[a-zA-Z][\w-]*[a-zA-Z]|[a-zA-Z]{3,}", cleaned)

    for word in words:
        w_lower = word.lower()
        if w_lower not in _STOP_WORDS and len(word) >= 3:
            keywords.append(word)

    return keywords[:5]


def _analyze_subreddit(sub, search_terms: list[str]) -> SubredditSignal | None:
    """Analyze a single subreddit for discovery signals.

    Collects: subscriber count, 30-day post volume estimate,
    average engagement (upvotes + comments), and relevance score.
    """
    try:
        sub_name = sub.display_name
        subscribers = sub.subscribers or 0

        # Get recent hot posts (limit=25 as per task spec)
        posts = list(sub.hot(limit=25))
        if not posts:
            return None

        # Determine which posts are within the last 30 days
        now = datetime.now(timezone.utc)
        recent_posts = []
        for post in posts:
            if post.stickied:
                continue
            post_time = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
            age_days = (now - post_time).days
            if age_days <= 30:
                recent_posts.append(post)

        # Estimate 30-day post volume from hot sample
        # Hot shows the most active recent posts — extrapolate
        if recent_posts:
            # If all 25 posts are within 30 days, the sub is very active
            # Use the proportion of recent posts × activity multiplier
            posts_30d = max(len(recent_posts), len(recent_posts) * 4)
        else:
            posts_30d = 0

        # Calculate average engagement (upvotes + comments per post)
        if recent_posts:
            total_engagement = sum(
                p.score + p.num_comments for p in recent_posts
            )
            avg_engagement = round(total_engagement / len(recent_posts), 1)
        else:
            avg_engagement = 0.0

        # Calculate topic relevance score (keyword overlap 0-100)
        relevance = _calculate_relevance(recent_posts or posts, search_terms)

        return SubredditSignal(
            name=f"r/{sub_name}",
            subscribers=subscribers,
            posts_30d=posts_30d,
            avg_engagement=avg_engagement,
            relevance_score=relevance,
        )

    except Exception as e:
        logger.debug("Subreddit analysis error for r/%s: %s", getattr(sub, "display_name", "?"), e)
        return None


def _calculate_relevance(posts, search_terms: list[str]) -> int:
    """Calculate topic relevance score (0-100) based on keyword overlap.

    Checks what proportion of posts contain at least one search term
    in their title or selftext.
    """
    if not posts or not search_terms:
        return 0

    terms_lower = [t.lower() for t in search_terms]
    matches = 0
    total_checked = min(len(posts), 25)

    for post in posts[:total_checked]:
        text = f"{post.title} {getattr(post, 'selftext', '')}".lower()
        for term in terms_lower:
            if term in text:
                matches += 1
                break  # One match per post is enough

    if total_checked == 0:
        return 0

    raw_score = (matches / total_checked) * 100
    return min(100, int(raw_score))


def _assess_no_signal(
    reddit,
    entities: list[DiscoveryEntity],
    narrow_terms: list[str],
    posts_found: int,
    start_time: float,
) -> NoSignalAssessment:
    """Assess no-signal condition and try broader search.

    If primary terms return <5 posts:
    - Try broader terms (parent category + industry entities)
    - If broader returns ≥10 posts → "search_too_narrow"
    - If broader also returns <5 → "topic_absent"
    """
    broader_found = _try_broader_search(reddit, entities, narrow_terms, start_time)

    if broader_found >= 10:
        return NoSignalAssessment(
            cause="search_too_narrow",
            explanation=(
                f"Only {posts_found} posts match specific hypothesis terms, "
                f"but {broader_found} posts found with broader industry/category terms. "
                f"The hypothesis may need rephrasing to match Reddit discussion patterns."
            ),
            suggestions=_suggest_broader_terms(entities),
        )
    else:
        return NoSignalAssessment(
            cause="topic_absent",
            explanation=(
                f"Only {posts_found} relevant posts found across all searched subreddits. "
                f"Broader terms also returned limited results ({broader_found} posts). "
                f"This topic has minimal Reddit presence."
            ),
            suggestions=_suggest_alternative_platforms(entities),
        )


def _try_broader_search(
    reddit,
    entities: list[DiscoveryEntity],
    narrow_terms: list[str],
    start_time: float,
) -> int:
    """Try broader search terms (parent categories, synonyms) to check if topic exists.

    Uses industry, audience, and problem entities as broader search terms.
    Returns estimated post count from broader search.
    """
    if time.time() - start_time > PER_HYPOTHESIS_TIMEOUT - 5:
        return 0

    # Build broader terms from industry/audience/problem entities
    broader_terms = []
    for e in entities:
        if e.category in ("industry", "audience", "problem"):
            broader_terms.append(e.name)

    if not broader_terms:
        return 0

    try:
        query = " ".join(broader_terms[:2])
        count = 0
        for sub in reddit.subreddits.search(query, limit=3):
            if time.time() - start_time > PER_HYPOTHESIS_TIMEOUT - 2:
                break
            try:
                for post in sub.hot(limit=10):
                    if not post.stickied:
                        count += 1
                if count >= 10:
                    break
            except Exception:
                continue
        return count
    except Exception as e:
        logger.debug("Broader search failed: %s", e)
        return 0


def _suggest_broader_terms(entities: list[DiscoveryEntity]) -> list[str]:
    """Suggest up to 3 adjacent Reddit topics when cause is 'search_too_narrow'."""
    suggestions = []
    for e in entities:
        if e.category == "industry":
            suggestions.append(f"Try broader industry term: '{e.name}'")
        elif e.category == "problem":
            suggestions.append(f"Try the problem angle: '{e.name}'")
        elif e.category == "audience":
            suggestions.append(f"Try targeting the audience: '{e.name}'")
        if len(suggestions) >= 3:
            break
    return suggestions[:3]


def _suggest_alternative_platforms(entities: list[DiscoveryEntity]) -> list[str]:
    """Suggest up to 3 alternative platforms when cause is 'topic_absent'."""
    suggestions = [
        "LinkedIn groups (professional B2B discussions may have more activity)",
        "Quora spaces (Q&A format often covers niche topics)",
        "Industry-specific forums or Slack communities",
    ]
    return suggestions[:3]
