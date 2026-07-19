"""
Test: Compare different Gemini models + prompt strategies for hobby comment quality.

Models:
  - gemini/gemini-2.5-flash (current, unstable today)
  - gemini/gemini-2.0-flash (previous stable)
  - gemini/gemini-2.5-flash-lite (cheap fallback)

All with plain text output (no JSON constraint).
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_config
from app.services.ai import call_llm

SYSTEM = """You are a casual Reddit commenter. Write a short comment (20-60 words) for the post below.

Rules:
- Sound like a real person on their phone
- One paragraph, no formatting
- Connect to specific details in the post
- No em-dashes, no brand mentions
- Don't start with "The/This/That/There/They"
- Must be a COMPLETE thought — never end mid-sentence

Voice: Casual data nerd, tracks biometrics, Austin TX runner.

Reply with ONLY the comment. Nothing else."""

USER = """r/whoop — "Is WHOOP's subscription model pushing boundaries, or has it become anti-consumer?"

Post: When you break down the math over a 5-year lifecycle, a user ends up paying $1,000 to $1,800. Zero Asset Ownership: the moment you stop paying, the band becomes a paperweight. Zero Resale Value. For that money you could buy two top-tier sports watches.

Top comment (2 upvotes): "It's genuinely a good product. I love to have a single hub of my data tracked 24/7."
"""


def test_model(model_name, count=10):
    print(f"\n{'─'*60}")
    print(f"  {model_name}")
    print(f"{'─'*60}")

    results = []
    for i in range(count):
        start = time.time()
        try:
            result = call_llm(
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": USER},
                ],
                model=model_name,
                temperature=0.9,
                max_tokens=200,
            )
            elapsed = int((time.time() - start) * 1000)
            content = (result["content"] or "").strip()

            # Strip quotes if wrapped
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1]

            words = len(content.split())
            # Quality: complete sentence ends with . ? ! or closing quote
            ends_complete = content and content[-1] in '.?!"\'' 
            
            ok = words >= 10 and ends_complete
            results.append({
                "ok": ok,
                "text": content,
                "words": words,
                "complete": ends_complete,
                "ms": elapsed,
            })

            status = "✓" if ok else "✗"
            flag = "" if ends_complete else " [INCOMPLETE]"
            print(f"  {i+1:2d}. {status} {elapsed:4d}ms [{words:2d}w]{flag} {content[:65]}")

        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            results.append({"ok": False, "text": "", "words": 0, "complete": False, "ms": elapsed})
            print(f"  {i+1:2d}. ✗ {elapsed:4d}ms ERROR: {str(e)[:60]}")

        time.sleep(1.5)

    # Stats
    successes = [r for r in results if r["ok"]]
    n = len(results)
    print(f"\n  Quality pass: {len(successes)}/{n} ({100*len(successes)/n:.0f}%)")
    print(f"  Complete sentences: {sum(1 for r in results if r['complete'])}/{n}")
    if successes:
        words = [r["words"] for r in successes]
        times = [r["ms"] for r in successes]
        print(f"  Words: avg={sum(words)//len(words)}, range=[{min(words)}-{max(words)}]")
        print(f"  Time: avg={sum(times)//len(times)}ms")

    return results


def main():
    print(f"\n{'='*60}")
    print(f"  GEMINI MODEL COMPARISON — hobby comment quality")
    print(f"  Plain text output, temperature=0.9")
    print(f"{'='*60}")

    models = [
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.0-flash",
        "gemini/gemini-2.5-flash-lite",
    ]

    all_results = {}
    for m in models:
        all_results[m] = test_model(m, count=10)
        time.sleep(3)

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    for m, results in all_results.items():
        ok = sum(1 for r in results if r["ok"])
        avg_ms = sum(r["ms"] for r in results) // len(results)
        print(f"  {m:35s} → {ok}/10 quality pass, avg {avg_ms}ms")


if __name__ == "__main__":
    main()
