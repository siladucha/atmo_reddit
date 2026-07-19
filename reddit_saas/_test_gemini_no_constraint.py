"""
Test: Gemini Flash WITH vs WITHOUT response_format=json_object

Group A: 10 calls WITH response_format={"type": "json_object"} (current behavior)
Group B: 10 calls WITHOUT response_format (free-form, rely on _extract_json parser)

Same prompt, same model, same temperature.
"""

import time
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_config
from app.services.ai import call_llm, _extract_json

# ─── Prompt ──────────────────────────────────────────────────────────────────

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
Post body: When you break down the math over a 5-year lifecycle, a user ends up paying $1,000 to $1,800. Zero Asset Ownership: the moment you stop paying, the band becomes a paperweight. Zero Resale Value.
Upvotes: 6
Top comments: [{"author": "keiranshell", "body": "It's genuinely a good product. I love to have a single hub of my data tracked 24/7.", "upvotes": 2}]"""

MESSAGES = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": USER},
]


def run_with_constraint(model):
    """Call with response_format=json_object (current production behavior)"""
    start = time.time()
    try:
        result = call_llm(
            messages=MESSAGES,
            model=model,
            temperature=0.85,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        elapsed = int((time.time() - start) * 1000)
        content = result["content"]
        
        if not content or not content.strip():
            return (False, "empty_content", elapsed, f"output_tokens={result.get('output_tokens')}")
        
        data = _extract_json(content)
        if data is None:
            return (False, f"parse_failed: {content[:80]}", elapsed, content[:150])
        
        comment = data.get("comment", "")
        if not comment:
            return (False, f"empty_comment: data={data}", elapsed, content[:150])
        
        return (True, comment, elapsed, None)
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        return (False, str(e)[:100], elapsed, None)


def run_without_constraint(model):
    """Call WITHOUT response_format — free-form response, parse manually"""
    start = time.time()
    try:
        result = call_llm(
            messages=MESSAGES,
            model=model,
            temperature=0.85,
            max_tokens=300,
            # NO response_format here
        )
        elapsed = int((time.time() - start) * 1000)
        content = result["content"]
        
        if not content or not content.strip():
            return (False, "empty_content", elapsed, f"output_tokens={result.get('output_tokens')}")
        
        data = _extract_json(content)
        if data is None:
            return (False, f"parse_failed: {content[:80]}", elapsed, content[:150])
        
        comment = data.get("comment", "")
        if not comment:
            return (False, f"empty_comment: data={data}", elapsed, content[:150])
        
        return (True, comment, elapsed, None)
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        return (False, str(e)[:100], elapsed, None)


def run_group(label, fn, count, model):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    
    results = []
    for i in range(count):
        ok, text, ms, debug = fn(model)
        results.append((ok, text, ms, debug))
        status = "✓" if ok else "✗"
        preview = text[:60]
        print(f"  {i+1:2d}. {status} {ms:4d}ms | {preview}")
        time.sleep(1)  # 1s between calls (fair for both groups)
    
    successes = sum(1 for r in results if r[0])
    times = [r[2] for r in results]
    success_times = [r[2] for r in results if r[0]]
    
    print(f"\n  Success: {successes}/{count} ({100*successes/count:.0f}%)")
    print(f"  Avg time: {sum(times)//count}ms (successful: {sum(success_times)//max(len(success_times),1)}ms)")
    
    # Show failures
    failures = [(r[1], r[3]) for r in results if not r[0]]
    if failures:
        print(f"  Failures:")
        for err, debug in failures:
            print(f"    - {err}")
    
    return results


def main():
    model = get_config("llm_scoring_model") or "gemini/gemini-2.5-flash"
    print(f"\n{'='*60}")
    print(f"  WITH vs WITHOUT response_format constraint")
    print(f"  Model: {model}")
    print(f"{'='*60}")

    # Group A: WITH constraint (current production)
    group_a = run_group(
        "GROUP A: WITH response_format={json_object} (current)",
        run_with_constraint, 10, model
    )

    print(f"\n  --- pause ---")
    time.sleep(3)

    # Group B: WITHOUT constraint (proposed fix)
    group_b = run_group(
        "GROUP B: WITHOUT response_format (free-form + parser)",
        run_without_constraint, 10, model
    )

    # Summary
    a_ok = sum(1 for r in group_a if r[0])
    b_ok = sum(1 for r in group_b if r[0])
    a_avg = sum(r[2] for r in group_a) // 10
    b_avg = sum(r[2] for r in group_b) // 10

    print(f"\n{'='*60}")
    print(f"  VERDICT")
    print(f"{'='*60}")
    print(f"  WITH constraint:    {a_ok}/10 success, avg {a_avg}ms")
    print(f"  WITHOUT constraint: {b_ok}/10 success, avg {b_avg}ms")
    
    if b_ok > a_ok:
        print(f"  → WITHOUT is better (+{b_ok - a_ok} successes)")
    elif a_ok > b_ok:
        print(f"  → WITH is better (+{a_ok - b_ok} successes)")
    else:
        print(f"  → Same success rate, check timing")


if __name__ == "__main__":
    main()
