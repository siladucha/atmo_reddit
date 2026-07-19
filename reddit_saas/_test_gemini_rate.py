"""
Test: Does Gemini Flash fail more under rapid-fire vs spaced requests?

Group A: 10 calls with 3s delay between each
Group B: 10 calls with 0s delay (back-to-back, like EPG build does)

Same prompt, same model, same parameters.
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_config
from app.services.ai import call_llm_json

# ─── Same prompt as EPG executor ─────────────────────────────────────────────

SYSTEM = """# Hobby & Karma Comment Writer

Generate a short, engaging Reddit comment. You're a regular person in a community you enjoy.

## Voice Profile
Casual, data-driven biohacker. Tracks HRV obsessively. Short punchy comments. Austin TX runner.

## Rules
1. 5-60 words max.
2. Sound like a person on their phone.
3. One paragraph only. No formatting.
4. Connect to specific details in the post.
5. No em-dashes.
6. No brand mentions.

## Output
Respond with a JSON object: {"comment": "your comment text here"}"""

USER = """Subreddit: r/whoop
Post title: Is WHOOP's subscription model pushing boundaries, or has it become anti-consumer?
Post body: When you break down the math over a 5-year lifecycle, a user ends up paying $1,000 to $1,800. Zero Asset Ownership: the moment you stop paying, the band becomes a paperweight. Zero Resale Value. For the cost of 5 years, you could buy two top-tier sports watches.
Upvotes: 6
Top comments: [{"author": "keiranshell", "body": "It's genuinely a good product. I love to have a single hub of my data tracked 24/7.", "upvotes": 2}]"""


def run_once(model):
    """Single call. Returns (success, comment_or_error, elapsed_ms, raw_content)"""
    start = time.time()
    try:
        result = call_llm_json(
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER},
            ],
            model=model,
            temperature=0.85,
            max_tokens=300,
        )
        elapsed = int((time.time() - start) * 1000)
        data = result.get("data", {})
        comment = data.get("comment", "")
        raw = result.get("content", "")
        if not comment:
            return (False, f"empty_comment (raw={raw[:60]})", elapsed, raw)
        return (True, comment, elapsed, raw)
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        return (False, str(e)[:100], elapsed, "")


def run_group(label, count, delay_sec, model):
    print(f"\n{'─'*60}")
    print(f"  {label}: {count} calls, {delay_sec}s delay between each")
    print(f"{'─'*60}")

    results = []
    for i in range(count):
        ok, text, ms, raw = run_once(model)
        results.append((ok, text, ms))
        status = "✓" if ok else "✗"
        preview = text[:55] if ok else text[:55]
        print(f"  {i+1:2d}. {status} {ms:5d}ms | {preview}")
        if i < count - 1 and delay_sec > 0:
            time.sleep(delay_sec)

    successes = sum(1 for r in results if r[0])
    times = [r[2] for r in results]
    print(f"\n  Result: {successes}/{count} success ({100*successes/count:.0f}%)")
    print(f"  Avg time: {sum(times)//count}ms")
    return results


def main():
    model = get_config("llm_scoring_model") or "gemini/gemini-2.5-flash"
    print(f"\n{'='*60}")
    print(f"  GEMINI RATE TEST — does spacing help?")
    print(f"  Model: {model}")
    print(f"{'='*60}")

    # Group A: spaced (3s between calls)
    group_a = run_group("GROUP A (3s delay)", 10, 3.0, model)

    print(f"\n  --- 5 second pause between groups ---")
    time.sleep(5)

    # Group B: rapid fire (no delay)
    group_b = run_group("GROUP B (no delay)", 10, 0.0, model)

    # Summary
    a_success = sum(1 for r in group_a if r[0])
    b_success = sum(1 for r in group_b if r[0])
    a_times = [r[2] for r in group_a]
    b_times = [r[2] for r in group_b]

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Group A (3s delay): {a_success}/10 success, avg {sum(a_times)//10}ms")
    print(f"  Group B (no delay): {b_success}/10 success, avg {sum(b_times)//10}ms")
    if a_success != b_success:
        print(f"  → Difference: {a_success - b_success} more successes with delay")
    else:
        print(f"  → No difference — rate is NOT the issue")


if __name__ == "__main__":
    main()
