"""
Test: Gemini Flash — JSON vs plain text output format.

Group A: "Respond with JSON: {"comment": "..."}" (current)
Group B: "Reply with ONLY the comment text. No formatting, no quotes, no preamble." (plaintext)

Hypothesis: Gemini wastes tokens on JSON structure and gets confused.
If we just ask for raw text — it'll be 100% reliable.
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_config
from app.services.ai import call_llm

# ─── Shared context ──────────────────────────────────────────────────────────

RULES = """## Rules
1. 5-60 words max (hard max 80).
2. Sound like a person typing on their phone.
3. One paragraph only. No formatting, no bullets, no bold.
4. Connect to specific details in the post.
5. No em-dashes (—).
6. No brand/product mentions.
7. Don't start with "The/This/That/There/They".
8. No filler closers like "Great post" or "Thanks for sharing".

## Voice
Casual, data-driven biohacker. Tracks HRV obsessively. Austin TX runner."""

USER = """Subreddit: r/whoop
Post title: Is WHOOP's subscription model pushing boundaries, or has it become anti-consumer?
Post body: When you break down the math over a 5-year lifecycle, a user ends up paying $1,000 to $1,800. Zero Asset Ownership: the moment you stop paying, the band becomes a paperweight.
Upvotes: 6
Top comments: [{"author": "keiranshell", "body": "It's genuinely a good product. I love to have a single hub of my data tracked 24/7.", "upvotes": 2}]"""

# ─── Prompt A: JSON output ───────────────────────────────────────────────────

SYSTEM_JSON = f"""# Hobby Comment Writer

Generate a short Reddit comment for a hobby subreddit.

{RULES}

## Output
Respond with a JSON object: {{"comment": "your comment text here"}}"""

# ─── Prompt B: Plain text output ─────────────────────────────────────────────

SYSTEM_PLAIN = f"""# Hobby Comment Writer

Generate a short Reddit comment for a hobby subreddit.

{RULES}

## Output
Reply with ONLY the comment text. Nothing else. No quotes, no labels, no markdown, no explanation. Just the comment itself."""

# ─── Runners ─────────────────────────────────────────────────────────────────

def run_json(model):
    start = time.time()
    try:
        result = call_llm(
            messages=[
                {"role": "system", "content": SYSTEM_JSON},
                {"role": "user", "content": USER},
            ],
            model=model,
            temperature=0.85,
            max_tokens=300,
        )
        elapsed = int((time.time() - start) * 1000)
        content = result["content"] or ""
        
        if not content.strip():
            return (False, "empty", elapsed, content)
        
        # Try to extract comment from JSON
        import json, re
        from app.services.ai import _extract_json
        data = _extract_json(content)
        if data and data.get("comment"):
            return (True, data["comment"], elapsed, None)
        
        return (False, f"no_comment: {content[:80]}", elapsed, content[:150])
    except Exception as e:
        return (False, str(e)[:80], int((time.time() - start) * 1000), None)


def run_plain(model):
    start = time.time()
    try:
        result = call_llm(
            messages=[
                {"role": "system", "content": SYSTEM_PLAIN},
                {"role": "user", "content": USER},
            ],
            model=model,
            temperature=0.85,
            max_tokens=300,
        )
        elapsed = int((time.time() - start) * 1000)
        content = result["content"] or ""
        
        if not content.strip():
            return (False, "empty", elapsed, content)
        
        # Clean up: strip quotes, leading "Comment:" prefix, etc.
        text = content.strip()
        # Remove wrapping quotes if present
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        # Remove common preamble
        for prefix in ["Comment:", "Here's my comment:", "Here is the comment:", "comment:"]:
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        
        words = len(text.split())
        if words < 3:
            return (False, f"too_short ({words}w): {text}", elapsed, content)
        
        return (True, text, elapsed, None)
    except Exception as e:
        return (False, str(e)[:80], int((time.time() - start) * 1000), None)


def run_group(label, fn, count, model):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    
    results = []
    for i in range(count):
        ok, text, ms, debug = fn(model)
        results.append((ok, text, ms))
        status = "✓" if ok else "✗"
        preview = text[:60]
        print(f"  {i+1:2d}. {status} {ms:4d}ms | {preview}")
        time.sleep(1)
    
    successes = sum(1 for r in results if r[0])
    times = [r[2] for r in results]
    print(f"\n  Success: {successes}/{count} ({100*successes/count:.0f}%)")
    print(f"  Avg time: {sum(times)//count}ms")
    
    if successes > 0:
        texts = [r[1] for r in results if r[0]]
        words = [len(t.split()) for t in texts]
        print(f"  Word count: avg={sum(words)//len(words)}, min={min(words)}, max={max(words)}")
    
    return results


def main():
    model = get_config("llm_scoring_model") or "gemini/gemini-2.5-flash"
    print(f"\n{'='*60}")
    print(f"  JSON vs PLAIN TEXT output format")
    print(f"  Model: {model}")
    print(f"{'='*60}")

    group_a = run_group("GROUP A: JSON output (current)", run_json, 10, model)
    
    print(f"\n  --- pause ---")
    time.sleep(3)
    
    group_b = run_group("GROUP B: PLAIN TEXT output (proposed)", run_plain, 10, model)

    a_ok = sum(1 for r in group_a if r[0])
    b_ok = sum(1 for r in group_b if r[0])

    print(f"\n{'='*60}")
    print(f"  VERDICT")
    print(f"{'='*60}")
    print(f"  JSON format:  {a_ok}/10 ({100*a_ok/10:.0f}%)")
    print(f"  Plain text:   {b_ok}/10 ({100*b_ok/10:.0f}%)")
    
    if b_ok > a_ok:
        print(f"  → PLAIN TEXT wins (+{b_ok - a_ok})")
    elif a_ok > b_ok:
        print(f"  → JSON wins (+{a_ok - b_ok})")
    else:
        print(f"  → Tie")
    
    # Show sample outputs from Group B
    if b_ok > 0:
        print(f"\n  Sample plain text outputs:")
        for r in group_b:
            if r[0]:
                print(f"    [{len(r[1].split())}w] {r[1]}")


if __name__ == "__main__":
    main()
