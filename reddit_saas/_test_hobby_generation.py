"""
Test: Hobby comment generation reliability.

Runs the same prompt N times against Gemini Flash (same as EPG executor)
and collects stats: success rate, failure reasons, response time, text quality.

Usage:
    cd reddit_saas
    python _test_hobby_generation.py --runs 100
    python _test_hobby_generation.py --runs 10  # quick check
"""

import argparse
import json
import time
import statistics
import sys
import os

# Ensure app imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_config
from app.services.ai import call_llm_json, call_llm


# ─── Test fixture: real hobby post from production ───────────────────────────

FIXTURE = {
    "subreddit": "whoop",
    "post_title": "Is WHOOP's subscription model pushing boundaries, or has it become anti-consumer? Let's talk numbers.",
    "post_body": (
        "I've been diving deep into the wearable market recently, and while WHOOP's metrics "
        "are undeniably fascinating, I find myself increasingly troubled by their business model. "
        "When you break down the math over a standard 5-year lifecycle, a user ends up paying "
        "anywhere from $1,000 to nearly $1,800 depending on the tier. That is an astronomical "
        "amount for a tracker. Zero Asset Ownership: the moment you stop paying WHOOP, the "
        "screenless band becomes a paperweight. Zero Resale Value: a used WHOOP has virtually "
        "zero resale value. For the cost of a 5-year WHOOP membership, a consumer could easily "
        "buy two top-tier dedicated sports watches."
    ),
    "post_ups": 6,
    "comments": '[{"author": "keiranshell", "body": "It\'s genuinely a good product. I don\'t use AI at all, but I love to have a single hub of my data which is tracked 24/7.", "depth": 0, "upvotes": 2}]',
}

VOICE_PROFILE = "Casual, data-driven biohacker. Tracks HRV obsessively. Prefers short punchy comments. Austin TX based runner and breathwork enthusiast."

PREV_COMMENTS = [
    "Yeah, that front-loaded curve is fascinating. My HRV data showed a similar pattern.",
    "Curious about the recovery boost though. Was it a really deep sleep session?",
    "4-7-8 works but honestly just extending the exhale does most of the heavy lifting.",
]


def build_prompt():
    """Build the same prompt as _generate_hobby_slot in epg_executor.py"""
    prev_section = "\n".join(f"- {c[:100]}" for c in PREV_COMMENTS[:5])

    system_prompt = f"""# Hobby & Karma Comment Writer

**Purpose:** Generate a short, engaging Reddit comment in a hobby subreddit. The single goal is karma: be the comment people upvote, reply to, and remember. You're a regular person participating in a community you enjoy.

## Voice Profile
{VOICE_PROFILE[:500]}

## Rules (NON-NEGOTIABLE)

1. **5-60 words** (hard max 80). If over 80, rewrite with a shorter idea.
2. **Sound like a person typing on their phone.** Not a content creator, not AI.
3. **One paragraph only.** No formatting, no bullets, no bold, no signatures.
4. **Connect to specific details** in the post. Generic comments that work on any thread = fail.
5. **No em-dashes (—).** Use commas, parentheses, or split the sentence.
6. **No brand/product mentions.** Zero tolerance.
7. **No "Th" sentence starters** (The, This, That, There, They). Rephrase.
8. **No gerund openers** (Trying, Looking, Getting). Anchor to a subject.
9. **Vary openers.** Don't start with "I [verb]..." every time.
10. **NEVER use filler closers** like "Respect for the analysis", "Great post", "Thanks for sharing". These are bot signatures.
11. **NEVER repeat a phrase** you used in a previous comment.

## Engagement Angles (pick ONE)

- **sharp_take** — opinionated observation nobody mentioned
- **yeah_and** — relatable agreement with a twist
- **useful_drop** — helpful tip delivered casually
- **micro_story** — ultra-short personal anecdote (specific moment, not narrative)
- **reality_check** — casual pushback on something off
- **question** — genuine question that sparks discussion

## Tone

Match the thread energy. Be casual, specific, concise, genuine. Never be a guru, teacher, or marketer. You're a casual participant, not an authority.

## Previous Comments (DO NOT repeat patterns or phrases from these):
{prev_section}

## Output

Respond with a JSON object: {{"comment": "your comment text here"}}"""

    user_prompt = f"""Subreddit: r/{FIXTURE['subreddit']}
Post title: {FIXTURE['post_title']}
Post body: {FIXTURE['post_body'][:500]}
Upvotes: {FIXTURE['post_ups']}
Top comments: {FIXTURE['comments'][:1500]}"""

    return system_prompt, user_prompt


def run_single(model: str, run_id: int) -> dict:
    """Run a single generation and return stats."""
    system_prompt, user_prompt = build_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    start = time.time()
    try:
        result = call_llm_json(
            messages=messages,
            model=model,
            temperature=0.85,
            max_tokens=300,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        data = result.get("data", {})
        comment = data.get("comment", "")
        raw_content = result.get("content", "")

        # Quality checks
        word_count = len(comment.split()) if comment else 0
        has_em_dash = "—" in comment
        too_short = word_count < 5
        too_long = word_count > 80
        starts_with_th = comment.strip().split()[0].lower() in ("the", "this", "that", "there", "they") if comment.strip() else False
        has_filler = any(f in comment.lower() for f in ["great post", "thanks for sharing", "respect for"])

        return {
            "run": run_id,
            "success": True,
            "comment": comment,
            "word_count": word_count,
            "elapsed_ms": elapsed_ms,
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "model_used": result.get("model", model),
            "quality_issues": [
                issue for issue, flag in [
                    ("too_short", too_short),
                    ("too_long", too_long),
                    ("em_dash", has_em_dash),
                    ("th_starter", starts_with_th),
                    ("filler_closer", has_filler),
                ] if flag
            ],
            "raw_content_preview": raw_content[:200] if raw_content != comment else None,
        }

    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "run": run_id,
            "success": False,
            "error": str(e)[:200],
            "elapsed_ms": elapsed_ms,
            "comment": None,
            "word_count": 0,
        }


def main():
    parser = argparse.ArgumentParser(description="Test hobby generation reliability")
    parser.add_argument("--runs", type=int, default=100, help="Number of runs")
    parser.add_argument("--model", type=str, default=None, help="Model override (default: llm_scoring_model from DB)")
    args = parser.parse_args()

    model = args.model or get_config("llm_scoring_model") or "gemini/gemini-2.5-flash"
    print(f"\n{'='*60}")
    print(f"  HOBBY GENERATION STRESS TEST")
    print(f"  Model: {model}")
    print(f"  Runs: {args.runs}")
    print(f"{'='*60}\n")

    results = []
    for i in range(args.runs):
        r = run_single(model, i + 1)
        results.append(r)

        # Progress
        status = "✓" if r["success"] else "✗"
        comment_preview = (r["comment"] or r.get("error", ""))[:60]
        issues = ",".join(r.get("quality_issues", []))
        issue_tag = f" [{issues}]" if issues else ""
        print(f"  {i+1:3d}/{args.runs} {status} {r['elapsed_ms']:5d}ms | {comment_preview}{issue_tag}")

        # Small delay to not hit rate limits
        if i < args.runs - 1:
            time.sleep(0.5)

    # ─── Stats ───────────────────────────────────────────────────────────────

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    times = [r["elapsed_ms"] for r in results]
    success_times = [r["elapsed_ms"] for r in successes]
    word_counts = [r["word_count"] for r in successes if r["word_count"] > 0]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Success rate: {len(successes)}/{args.runs} ({100*len(successes)/args.runs:.1f}%)")
    print(f"  Failure rate: {len(failures)}/{args.runs} ({100*len(failures)/args.runs:.1f}%)")

    if times:
        print(f"\n  Response time (all):")
        print(f"    avg: {statistics.mean(times):.0f}ms")
        print(f"    p50: {statistics.median(times):.0f}ms")
        print(f"    p95: {sorted(times)[int(len(times)*0.95)]:.0f}ms")
        print(f"    min: {min(times)}ms  max: {max(times)}ms")

    if word_counts:
        print(f"\n  Word count (successful):")
        print(f"    avg: {statistics.mean(word_counts):.1f}")
        print(f"    min: {min(word_counts)}  max: {max(word_counts)}")
        in_range = sum(1 for w in word_counts if 5 <= w <= 80)
        print(f"    in 5-80 range: {in_range}/{len(word_counts)} ({100*in_range/len(word_counts):.0f}%)")

    # Quality issues breakdown
    all_issues = []
    for r in successes:
        all_issues.extend(r.get("quality_issues", []))
    if all_issues:
        from collections import Counter
        issue_counts = Counter(all_issues)
        print(f"\n  Quality issues (in {len(successes)} successful):")
        for issue, count in issue_counts.most_common():
            print(f"    {issue}: {count} ({100*count/len(successes):.0f}%)")

    # Failure reasons
    if failures:
        print(f"\n  Failure reasons:")
        from collections import Counter
        error_types = Counter()
        for f in failures:
            err = f.get("error", "unknown")
            # Simplify error
            if "empty response" in err.lower():
                error_types["empty_response"] += 1
            elif "non-json" in err.lower():
                error_types["non_json_response"] += 1
            elif "timeout" in err.lower():
                error_types["timeout"] += 1
            else:
                error_types[err[:50]] += 1
        for err, count in error_types.most_common():
            print(f"    {err}: {count}")

    # Sample outputs
    print(f"\n  Sample comments (first 5 successful):")
    for r in successes[:5]:
        print(f"    [{r['word_count']}w] {r['comment']}")

    # Save full results to file
    output_file = f"_test_results_hobby_gen_{int(time.time())}.json"
    with open(output_file, "w") as f:
        json.dump({
            "model": model,
            "runs": args.runs,
            "success_rate": len(successes) / args.runs,
            "avg_time_ms": statistics.mean(times) if times else 0,
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Full results saved to: {output_file}")


if __name__ == "__main__":
    main()
