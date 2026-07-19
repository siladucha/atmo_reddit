"""Test which models produce reliable JSON for hobby comments."""
import litellm
import json
import time

models_to_test = [
    "gemini/gemini-2.5-flash",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-4-6",
]

system = """You are a casual Reddit commenter. Generate a short comment (15-40 words).
Return ONLY a JSON object: {"comment": "your text"}
No markdown. No code blocks. No explanation. Just the JSON object."""

user = """Subreddit: r/productivity
Post title: How do you stay focused when working from home?
Post body: I've been WFH for 2 years and still struggle with distractions. What works for you?
Upvotes: 47

Return JSON only: {"comment": "..."}"""

msgs = [
    {"role": "system", "content": system},
    {"role": "user", "content": user},
]

print("=" * 70)
print("MODEL COMPARISON: JSON reliability for hobby comments")
print("=" * 70)

for model in models_to_test:
    print(f"\n--- {model} (5 attempts) ---")
    successes = 0
    failures = []
    times = []
    
    for i in range(5):
        start = time.time()
        try:
            r = litellm.completion(
                model=model,
                messages=msgs,
                max_tokens=150,
                temperature=0.8,
                response_format={"type": "json_object"},
            )
            elapsed = time.time() - start
            times.append(elapsed)
            content = (r.choices[0].message.content or "").strip()
            
            # Check quality
            has_markdown = "```" in content
            try:
                parsed = json.loads(content)
                comment = parsed.get("comment", "")
                if comment and len(comment) > 5 and not has_markdown:
                    successes += 1
                    words = len(comment.split())
                    first = comment.split()[0].lower()
                    em = "\u2014" in comment
                    th = first in ("the", "this", "that", "there", "they")
                    print(f"  {i+1}. OK [{words}w{'/TH' if th else ''}{'/EM' if em else ''}] {comment[:80]}")
                else:
                    failures.append(f"empty_or_markdown: {content[:60]}")
                    print(f"  {i+1}. BAD: {content[:60]}")
            except json.JSONDecodeError:
                failures.append(f"json_fail: {content[:60]}")
                print(f"  {i+1}. JSON_FAIL: {content[:60]}")
        except Exception as e:
            elapsed = time.time() - start
            times.append(elapsed)
            failures.append(f"error: {str(e)[:40]}")
            print(f"  {i+1}. ERROR: {str(e)[:60]}")
    
    avg_time = sum(times) / len(times) if times else 0
    print(f"  Result: {successes}/5 success | avg {avg_time:.1f}s | failures: {len(failures)}")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)
