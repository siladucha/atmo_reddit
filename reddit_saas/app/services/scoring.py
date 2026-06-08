"""Thread scoring service.

Uses a cheap LLM (Haiku/Flash) to evaluate Reddit threads for relevance,
quality, and strategic value to a client.

Supports two modes:
1. Single-thread scoring (legacy, fallback)
2. Batch scoring — sends up to 10 threads per LLM call (5x faster, same cost)

Refactored for shared subreddit registry: scoring writes to ThreadScore
(per-client) instead of directly on RedditThread.
"""

from app.logging_config import get_logger
import uuid

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.client import Client
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.services.ai import call_llm_json, log_ai_usage
from app.schemas.llm_outputs import ScoringOutput, BatchScoringOutput

logger = get_logger(__name__)

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
            max_tokens=2048,
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


BATCH_SCORING_PROMPT = """You are a content analyst expert and online discussions thread Classifier.

Evaluate MULTIPLE discussion threads to determine which ones deserve human attention and potential engagement.

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

You will receive multiple threads numbered [0], [1], [2], etc.
Return a JSON object with a "results" array containing one result per thread, in order:

{{
  "results": [
    {{
      "thread_index": 0,
      "alert": true/false,
      "tag": "engage" | "monitor" | "skip",
      "relevance": 0-3,
      "quality": 0-3,
      "strategic": 0-3,
      "composite": 0-9,
      "intent": "help_seeking" | "comparison" | "opinion_forming" | "venting" | "announcement" | "other",
      "reason": "<15 word explanation>"
    }},
    ...
  ]
}}

IMPORTANT: Return exactly one result per thread, in the same order as input. thread_index must match the input numbering."""


def score_threads_batch(
    db: Session,
    threads: list[RedditThread],
    client: Client,
    batch_size: int = 10,
) -> list[ThreadScore]:
    """Score multiple threads in batched LLM calls.

    Sends up to batch_size threads per LLM call, dramatically reducing
    HTTP overhead and latency. Falls back to single-thread scoring on failure.

    Args:
        db: Database session.
        threads: List of threads to score.
        client: Client context for scoring.
        batch_size: Max threads per LLM call (default 10).

    Returns:
        List of created/updated ThreadScore records.
    """
    if not threads:
        return []

    all_scores: list[ThreadScore] = []

    # Process in batches
    for i in range(0, len(threads), batch_size):
        batch = threads[i:i + batch_size]

        try:
            scores = _score_batch(db, batch, client)
            all_scores.extend(scores)
        except Exception as e:
            logger.warning(
                f"Batch scoring failed for batch {i//batch_size + 1}, "
                f"falling back to single-thread scoring: {e}"
            )
            # Fallback: score one by one
            for thread in batch:
                try:
                    score = score_thread_for_client(db, thread, client)
                    all_scores.append(score)
                except Exception as single_err:
                    logger.error(f"Single-thread scoring also failed for {thread.id}: {single_err}")
                    continue

    return all_scores


def _score_batch(
    db: Session,
    threads: list[RedditThread],
    client: Client,
) -> list[ThreadScore]:
    """Score a single batch of threads in one LLM call.

    Args:
        db: Database session.
        threads: Batch of threads (max ~10).
        client: Client context.

    Returns:
        List of ThreadScore records.

    Raises:
        RuntimeError: If LLM call or parsing fails.
    """
    # Build the batch user message
    thread_sections = []
    for idx, thread in enumerate(threads):
        section = f"""[{idx}] Subreddit: r/{thread.subreddit}
Title: {thread.post_title}
Post: {(thread.post_body or '(no body)')[:800]}
Comments: {(thread.comments_json or '(no comments)')[:1500]}
---"""
        thread_sections.append(section)

    user_content = "\n\n".join(thread_sections)

    system_prompt = BATCH_SCORING_PROMPT.format(
        brand_name=client.brand_name,
        company_profile=client.company_profile or "",
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
        competitive_landscape=client.competitive_landscape or "",
        keywords=str(client.keywords or []),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=get_config("llm_scoring_model"),
            temperature=0.2,
            max_tokens=2048 * len(threads),  # Scale output tokens with batch size (includes thinking tokens for Gemini 2.5)
            schema=BatchScoringOutput,
        )
    except Exception as e:
        raise RuntimeError(f"Batch scoring LLM failed: {e}") from e

    # Log AI usage (once per batch)
    try:
        log_ai_usage(
            db, str(client.id), "scoring_batch", result,
            subreddit_name=f"batch_{len(threads)}",
        )
    except Exception:
        logger.warning("Failed to log AI usage for batch scoring")

    # Parse results and create ThreadScore records
    batch_data = result["data"]
    results_list = batch_data.get("results", [])

    scores: list[ThreadScore] = []
    for item in results_list:
        idx = item.get("thread_index", -1)
        if idx < 0 or idx >= len(threads):
            logger.warning(f"Batch scoring returned invalid thread_index={idx}")
            continue

        thread = threads[idx]
        thread_score = _upsert_thread_score(db, thread, client, item)
        scores.append(thread_score)

    db.commit()

    # Check if we got results for all threads
    scored_ids = {s.thread_id for s in scores}
    for thread in threads:
        if thread.id not in scored_ids:
            logger.warning(
                f"Batch scoring missed thread {thread.id} "
                f"('{thread.post_title[:40]}'), will retry individually"
            )
            try:
                score = score_thread_for_client(db, thread, client)
                scores.append(score)
            except Exception:
                pass

    logger.info(
        f"Batch scored {len(scores)}/{len(threads)} threads for {client.client_name}"
    )
    return scores


def _upsert_thread_score(
    db: Session,
    thread: RedditThread,
    client: Client,
    data: dict,
) -> ThreadScore:
    """Create or update a ThreadScore record from scoring data."""
    existing = (
        db.query(ThreadScore)
        .filter(
            ThreadScore.thread_id == thread.id,
            ThreadScore.client_id == client.id,
        )
        .first()
    )

    fields = {
        "tag": data.get("tag", "skip"),
        "alert": data.get("alert", False),
        "relevance": data.get("relevance", 0),
        "quality": data.get("quality", 0),
        "strategic": data.get("strategic", 0),
        "composite": data.get("composite", 0),
        "intent": data.get("intent", "other"),
        "scoring_reasoning": data.get("reason", ""),
    }

    if existing:
        for key, val in fields.items():
            setattr(existing, key, val)
        return existing
    else:
        thread_score = ThreadScore(
            thread_id=thread.id,
            client_id=client.id,
            **fields,
        )
        db.add(thread_score)
        return thread_score


def _get_all_subreddit_ids_for_scoring(
    db: Session,
    client: Client,
    avatar=None,
) -> list:
    """Get all subreddit IDs relevant for scoring: client assignments + avatar hobby subs.

    Returns a list of subreddit UUIDs that includes:
    - All active ClientSubredditAssignment subreddits for the client
    - All hobby subreddits from the avatar (looked up in Subreddit registry)
    """
    from sqlalchemy import func as sa_func

    # Business subreddits from client assignments
    assigned_ids = [
        row[0]
        for row in db.query(ClientSubredditAssignment.subreddit_id)
        .filter(
            ClientSubredditAssignment.client_id == client.id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    ]

    # Hobby subreddits from avatar (resolve names to IDs via Subreddit registry)
    if avatar:
        hobby_names = []
        hobby_raw = avatar.hobby_subreddits or []
        if isinstance(hobby_raw, str):
            hobby_raw = [s.strip() for s in hobby_raw.split(",")]
        for item in hobby_raw:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or item.get("display_name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                hobby_names.append(name.lower())

        if hobby_names:
            hobby_sub_ids = [
                row[0]
                for row in db.query(Subreddit.id)
                .filter(sa_func.lower(Subreddit.subreddit_name).in_(hobby_names))
                .all()
            ]
            # Merge without duplicates
            existing_set = set(assigned_ids)
            for sid in hobby_sub_ids:
                if sid not in existing_set:
                    assigned_ids.append(sid)
                    existing_set.add(sid)

    return assigned_ids


def score_unscored_threads_for_client(
    db: Session,
    client: Client,
    max_threads: int = 200,
    max_age_hours: int = 72,
    max_to_score: int = 20,
    avatar=None,
) -> dict:
    """Score unscored threads for a client using pre-filter + batch scoring.

    Pipeline:
    1. Pull ALL unscored threads from client's subreddits (up to max_threads)
    2. Pre-filter: keyword/competitor/engagement matching (free, instant)
    3. Only candidates (typically 10-20 out of 200) go to LLM in batches
    4. Return detailed results for UI display

    The key insight: we can afford to scan 200 threads with regex (< 5ms)
    but we only want to send 10-20 to LLM ($0.0003 each, 1-2s each).

    Args:
        db: Database session.
        client: The client to score threads for.
        max_threads: Maximum threads to pull from DB for pre-filtering.
        max_age_hours: Ignore threads older than this.
        max_to_score: Maximum candidates to send to LLM after pre-filter.
        avatar: Optional avatar — if provided, includes hobby subreddits.

    Returns:
        Dict with scoring results:
        {
            "scored": int,
            "engage": int,
            "monitor": int,
            "skip": int,
            "pre_filtered_out": int,
            "growth_opportunities": int,
            "total_unscored": int,
            "scores": list[ThreadScore],
            "growth_threads": list[RedditThread],
            "skipped_threads": list[dict],
        }
    """
    from datetime import datetime, timezone, timedelta
    from app.services.pre_filter import pre_filter_threads

    freshness_cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    # Get all relevant subreddit IDs (client assignments + avatar hobby subs)
    all_subreddit_ids = _get_all_subreddit_ids_for_scoring(db, client, avatar)

    if not all_subreddit_ids:
        logger.info(f"No subreddits found for scoring. Client: {client.client_name}")
        return {
            "scored": 0, "engage": 0, "monitor": 0, "skip": 0,
            "pre_filtered_out": 0, "growth_opportunities": 0,
            "total_unscored": 0, "scores": [], "growth_threads": [],
            "skipped_threads": [],
        }

    # Find ALL unscored threads across all subreddits (we filter locally, not via LLM)
    scored_thread_ids = (
        db.query(ThreadScore.thread_id)
        .filter(ThreadScore.client_id == client.id)
    )

    unscored = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id.in_(all_subreddit_ids),
            RedditThread.is_locked.is_(False),
            RedditThread.scraped_at >= freshness_cutoff,
            ~RedditThread.id.in_(scored_thread_ids),
        )
        .order_by(RedditThread.scraped_at.desc())
        .limit(max_threads)
        .all()
    )

    total_unscored_estimate = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id.in_(all_subreddit_ids),
            RedditThread.is_locked.is_(False),
            ~RedditThread.id.in_(scored_thread_ids),
        )
        .count()
    )

    if not unscored:
        return {
            "scored": 0, "engage": 0, "monitor": 0, "skip": 0,
            "pre_filtered_out": 0, "growth_opportunities": 0,
            "total_unscored": total_unscored_estimate,
            "scores": [], "growth_threads": [], "skipped_threads": [],
        }

    # Step 1: Pre-filter ALL threads (free, < 10ms for 200 threads)
    # Only max_to_score candidates will be sent to LLM
    filter_result = pre_filter_threads(
        unscored, client, max_candidates=max_to_score
    )

    logger.info(
        f"Pre-filter: {len(unscored)} threads scanned → "
        f"{filter_result.candidates_count} candidates for LLM, "
        f"{filter_result.growth_count} growth, "
        f"{filter_result.skipped_count} skipped. "
        f"Client: {client.client_name}"
    )

    # Step 2: Batch score only the candidates via LLM
    scores: list[ThreadScore] = []
    if filter_result.candidates:
        scores = score_threads_batch(db, filter_result.candidates, client)

    # Count results by tag
    engage_count = sum(1 for s in scores if s.tag == "engage")
    monitor_count = sum(1 for s in scores if s.tag == "monitor")
    skip_count = sum(1 for s in scores if s.tag == "skip")

    logger.info(
        f"Scored {len(scores)} threads for client {client.client_name}: "
        f"{engage_count} engage, {monitor_count} monitor, {skip_count} skip. "
        f"Pre-filtered out: {filter_result.skipped_count}, "
        f"Growth opportunities: {filter_result.growth_count}"
    )

    return {
        "scored": len(scores),
        "engage": engage_count,
        "monitor": monitor_count,
        "skip": skip_count,
        "pre_filtered_out": filter_result.skipped_count,
        "growth_opportunities": filter_result.growth_count,
        "total_unscored": total_unscored_estimate,
        "scores": scores,
        "growth_threads": filter_result.growth_opportunities,
        "skipped_threads": filter_result.skipped,
    }


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
    Returns int (count) for backward compat.
    """
    result = score_unscored_threads_for_client(db, client)
    if isinstance(result, dict):
        return result.get("scored", 0)
    return result
