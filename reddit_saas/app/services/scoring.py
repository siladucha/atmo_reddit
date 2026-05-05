"""Thread scoring service.

Uses a cheap LLM (Haiku/Flash) to evaluate Reddit threads for relevance,
quality, and strategic value to a client.
"""

import logging

from sqlalchemy.orm import Session

from app.config import get_config
from app.models.client import Client
from app.models.thread import RedditThread
from app.services.ai import call_llm_json, log_ai_usage

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
    (score_thread) and the dry-run preview UI.
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


def apply_scoring_result(db: Session, thread: RedditThread, data: dict) -> None:
    """Apply parsed scoring JSON to a thread and commit.

    Used by both live scoring and dry-run paste-back.
    """
    thread.tag = data.get("tag", "skip")
    thread.alert = data.get("alert", False)
    thread.relevance = data.get("relevance", 0)
    thread.quality = data.get("quality", 0)
    thread.strategic = data.get("strategic", 0)
    thread.composite = data.get("composite", 0)
    thread.intent = data.get("intent", "other")
    thread.scoring_reasoning = data.get("reason", "")
    db.commit()


def score_thread(db: Session, thread: RedditThread, client: Client) -> dict:
    """Score a single thread using AI.

    Args:
        db: Database session
        thread: The thread to score
        client: The client context for scoring

    Returns:
        Scoring result dict
    """
    messages = build_scoring_messages(thread, client)

    result = call_llm_json(
        messages=messages,
        model=get_config("llm_scoring_model"),
        temperature=0.2,
        max_tokens=256,
    )

    log_ai_usage(db, str(client.id), "scoring", result)

    data = result["data"]
    apply_scoring_result(db, thread, data)

    logger.info(
        f"Scored thread '{thread.post_title[:50]}' → "
        f"tag={thread.tag}, composite={thread.composite}, alert={thread.alert}"
    )

    return data


def score_unscored_threads(db: Session, client: Client) -> int:
    """Score all unscored threads for a client.

    Returns:
        Number of threads scored.
    """
    unscored = (
        db.query(RedditThread)
        .filter(
            RedditThread.client_id == client.id,
            RedditThread.tag.is_(None),
        )
        .all()
    )

    count = 0
    for thread in unscored:
        try:
            score_thread(db, thread, client)
            count += 1
        except Exception as e:
            logger.error(f"Failed to score thread {thread.id}: {e}")
            continue

    logger.info(f"Scored {count}/{len(unscored)} threads for client {client.client_name}")
    return count
