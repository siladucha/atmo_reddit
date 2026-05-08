"""Thread scoring service.

Uses a cheap LLM (Haiku/Flash) to evaluate Reddit threads for relevance,
quality, and strategic value to a client.

Refactored for shared subreddit registry: scoring writes to ThreadScore
(per-client) instead of directly on RedditThread.
"""

import logging
import uuid

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.client import Client
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.services.ai import call_llm_json, log_ai_usage
from app.schemas.llm_outputs import ScoringOutput

logger = logging.getLogger(__name__)

SCORING_PROMPT = """You are a content analyst expert and online discussions thread Classifier.

Evaluate discussion threads to determine which ones deserve human attention and potential engagement.

**Important context**: We engage as regular individuals sharing opinions and expertise — NOT as official company representatives.

---

## Context

<company_overview>
Brand: {brand_name}
Overview: {company_profile}
Worldview: {company_worldview}
Problem we solve: {company_problem}
Competitors: {competitive_landscape}
Keywords: {keywords}
</company_overview>

---

## Evaluation Framework

### 1. Topic Relevance (Score 0-3)
| Score | Criteria |
|-------|----------|
| 0 | Off-topic — different industry entirely |
| 1 | Adjacent — in our general space but not our specific domain |
| 2 | In-domain — discusses topics within our world of content |
| 3 | Direct hit — discusses our exact domain, core terms, or a direct competitor |

### 2. Discussion Quality (Score 0-3)
| Score | Criteria |
|-------|----------|
| 0 | Noise — spam, trolling, dead thread |
| 1 | Low quality — shallow, mostly memes/jokes |
| 2 | Decent discussion — real conversation happening |
| 3 | High quality — substantive discussion, genuine debate |

### 3. Discussion Intent
| Intent | Description |
|--------|-------------|
| help_seeking | Asking for solutions or guidance |
| comparison | Evaluating options, "X vs Y" |
| opinion_forming | Discussing trends, best practices |
| venting | Complaining, not seeking solutions |
| announcement | Sharing news |
| other | Doesn't fit above |

### 4. Strategic Value (Score 0-3)
| Score | Criteria |
|-------|----------|
| 0 | No strategic value |
| 1 | Low value — tangentially related |
| 2 | Market education opportunity — can educate about the right approach |
| 3 | High strategic value — directly involves our differentiators or competitor weakness |

---

## Decision Logic

Composite = relevance + quality + strategic (0-9)

| Composite | Tag |
|-----------|-----|
| 7-9 | engage (+ alert: true) |
| 5-6 | engage |
| 3-4 | monitor |
| 0-2 | skip |

Override: If company or competitor mentioned AND relevance >= 2 → alert: true, tag: engage

---

## Output

Return JSON only:
{{
  "alert": true/false,
  "tag": "engage" | "monitor" | "skip",
  "relevance": 0-3,
  "quality": 0-3,
  "strategic": 0-3,
  "composite": 0-9,
  "intent": "help_seeking" | "comparison" | "opinion_forming" | "venting" | "announcement" | "other",
  "reason": "<15 word explanation>"
}}"""


def build_scoring_messages(thread: RedditThread, client: Client) -> list[dict]:
    """Render the full system+user message pair for thread scoring.

    Pure function: no LLM call, no DB writes. Used by both the live pipeline
    (score_thread_for_client) and the dry-run preview UI.

    Gets subreddit name from the denormalized `thread.subreddit` field.
    """
    thread_content = f"""<subreddit>
r/{thread.subreddit}
</subreddit>

<full_thread>
Title: {thread.post_title}

Post: {thread.post_body or '(no body)'}

Comments: {thread.comments_json or '(no comments)'}
</full_thread>"""

    system_prompt = SCORING_PROMPT.format(
        brand_name=client.brand_name,
        company_profile=client.company_profile or "",
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
        competitive_landscape=client.competitive_landscape or "",
        keywords=str(client.keywords or []),
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": thread_content},
    ]


def score_thread_for_client(
    db: Session,
    thread: RedditThread,
    client: Client,
) -> ThreadScore:
    """Score a single thread for a specific client. Creates ThreadScore record.

    Uses AI to evaluate the thread and writes the result to the thread_scores
    table instead of directly on RedditThread.

    Args:
        db: Database session.
        thread: The thread to score.
        client: The client context for scoring.

    Returns:
        The created or updated ThreadScore record.

    Raises:
        RuntimeError: If LLM call fails.
    """
    messages = build_scoring_messages(thread, client)

    try:
        result = call_llm_json(
            messages=messages,
            model=get_config("llm_scoring_model"),
            temperature=0.2,
            max_tokens=256,
            schema=ScoringOutput,
        )
    except Exception as e:
        logger.error(
            f"LLM call failed in score_thread_for_client for thread "
            f"'{thread.post_title[:50]}' client={client.client_name}: {e}"
        )
        raise RuntimeError(f"Thread scoring LLM failed: {e}") from e

    try:
        log_ai_usage(
            db, str(client.id), "scoring", result,
            thread_id=str(thread.id),
            subreddit_name=thread.subreddit,
        )
    except Exception:
        logger.warning("Failed to log AI usage for scoring")

    data = result["data"]

    # Upsert ThreadScore — update if exists, create if not
    existing_score = (
        db.query(ThreadScore)
        .filter(
            ThreadScore.thread_id == thread.id,
            ThreadScore.client_id == client.id,
        )
        .first()
    )

    if existing_score:
        existing_score.tag = data.get("tag", "skip")
        existing_score.alert = data.get("alert", False)
        existing_score.relevance = data.get("relevance", 0)
        existing_score.quality = data.get("quality", 0)
        existing_score.strategic = data.get("strategic", 0)
        existing_score.composite = data.get("composite", 0)
        existing_score.intent = data.get("intent", "other")
        existing_score.scoring_reasoning = data.get("reason", "")
        db.commit()
        db.refresh(existing_score)
        thread_score = existing_score
    else:
        thread_score = ThreadScore(
            thread_id=thread.id,
            client_id=client.id,
            tag=data.get("tag", "skip"),
            alert=data.get("alert", False),
            relevance=data.get("relevance", 0),
            quality=data.get("quality", 0),
            strategic=data.get("strategic", 0),
            composite=data.get("composite", 0),
            intent=data.get("intent", "other"),
            scoring_reasoning=data.get("reason", ""),
        )
        db.add(thread_score)
        db.commit()
        db.refresh(thread_score)

    logger.info(
        f"Scored thread '{thread.post_title[:50]}' for client {client.client_name} → "
        f"tag={thread_score.tag}, composite={thread_score.composite}, alert={thread_score.alert}"
    )

    return thread_score


def score_unscored_threads_for_client(db: Session, client: Client) -> int:
    """Score all threads in client's assigned subreddits that lack a ThreadScore.

    Finds threads via the client's active subreddit assignments, then checks
    which ones don't have a ThreadScore record for this client.

    Args:
        db: Database session.
        client: The client to score threads for.

    Returns:
        Number of threads scored.
    """
    # Get subreddit IDs for this client's active assignments
    assigned_subreddit_ids = (
        db.query(ClientSubredditAssignment.subreddit_id)
        .filter(
            ClientSubredditAssignment.client_id == client.id,
            ClientSubredditAssignment.is_active.is_(True),
        )
    )

    # Find threads in those subreddits that don't have a ThreadScore for this client
    scored_thread_ids = (
        db.query(ThreadScore.thread_id)
        .filter(ThreadScore.client_id == client.id)
    )

    unscored = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id.in_(assigned_subreddit_ids),
            RedditThread.is_locked.is_(False),
            ~RedditThread.id.in_(scored_thread_ids),
        )
        .all()
    )

    count = 0
    for thread in unscored:
        try:
            score_thread_for_client(db, thread, client)
            count += 1
        except Exception as e:
            logger.error(f"Failed to score thread {thread.id}: {e}")
            continue

    logger.info(f"Scored {count}/{len(unscored)} threads for client {client.client_name}")
    return count


def get_client_threads_with_scores(
    db: Session,
    client_id: uuid.UUID,
    tag: str | None = None,
    limit: int = 200,
) -> list[tuple[RedditThread, ThreadScore]]:
    """Return threads with their per-client scores for display.

    Joins RedditThread with ThreadScore for the given client. Optionally
    filters by tag.

    Args:
        db: Database session.
        client_id: The client whose scores to retrieve.
        tag: Optional tag filter (engage, monitor, skip).
        limit: Maximum number of results to return (default 200).

    Returns:
        A list of (RedditThread, ThreadScore) tuples ordered by scored_at desc.
    """
    query = (
        db.query(RedditThread, ThreadScore)
        .join(ThreadScore, and_(
            ThreadScore.thread_id == RedditThread.id,
            ThreadScore.client_id == client_id,
        ))
    )

    if tag:
        query = query.filter(ThreadScore.tag == tag)

    query = query.order_by(ThreadScore.scored_at.desc()).limit(limit)

    return query.all()


# ---------------------------------------------------------------------------
# Legacy compatibility functions (kept for backward compatibility during
# transition; will be removed once all callers are updated)
# ---------------------------------------------------------------------------


def apply_scoring_result(db: Session, thread: RedditThread, data: dict) -> None:
    """Legacy: Apply parsed scoring JSON to a thread and commit.

    DEPRECATED — use score_thread_for_client instead.
    Kept for backward compatibility with dry-run UI.
    """
    # For legacy callers that still expect scoring on the thread directly,
    # we just log a warning. The thread model no longer has scoring fields.
    logger.warning(
        "apply_scoring_result called on thread %s — this is deprecated. "
        "Use score_thread_for_client instead.",
        thread.id,
    )


def score_thread(db: Session, thread: RedditThread, client: Client) -> dict:
    """Legacy: Score a single thread using AI.

    DEPRECATED — use score_thread_for_client instead.
    Kept for backward compatibility.
    """
    thread_score = score_thread_for_client(db, thread, client)
    return {
        "tag": thread_score.tag,
        "alert": thread_score.alert,
        "relevance": thread_score.relevance,
        "quality": thread_score.quality,
        "strategic": thread_score.strategic,
        "composite": thread_score.composite,
        "intent": thread_score.intent,
        "reason": thread_score.scoring_reasoning,
    }


def score_unscored_threads(db: Session, client: Client) -> int:
    """Legacy: Score all unscored threads for a client.

    DEPRECATED — use score_unscored_threads_for_client instead.
    Kept for backward compatibility with ai_pipeline.py.
    """
    return score_unscored_threads_for_client(db, client)
