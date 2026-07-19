"""Test Claude Sonnet for hobby comments via RAMP call_llm_json."""
import sys
sys.path.insert(0, '/app')

from app.services.ai import call_llm_json
from app.database import SessionLocal
from app.config import get_config
import time

db = SessionLocal()

# Use the actual generation model (Claude Sonnet)
model = get_config("llm_generation_model")
print(f"Testing: {model} (10 calls)\n")

system = """# Hobby & Karma Comment Writer

Generate a short, engaging Reddit comment. The single goal: be the comment people upvote.

## Rules (NON-NEGOTIABLE)
1. 5-60 words (hard max 80).
2. Sound like a person typing on their phone.
3. One paragraph only. No formatting.
4. Connect to specific details in the post.
5. No em-dashes.
6. No "Th" sentence starters (The, This, That, There, They).
7. No gerund openers (Trying, Looking, Getting).
8. NEVER use filler closers like "Great post", "Thanks for sharing".

## Output
Return JSON: {"comment": "your text here"}"""

user = """Subreddit: r/productivity
Post title: How do you stay focused when working from home?
Post body: I've been WFH for 2 years and still struggle with distractions. My biggest enemy is my phone.
Upvotes: 47
Top comments: "Pomodoro changed my life" (score: 12), "I put my phone in another room" (score: 8)

Return: {"comment": "..."}"""

msgs = [
    {"role": "system", "content": system},
    {"role": "user", "content": user},
]

ok = 0
violations = {"th": 0, "ing": 0, "em": 0, "json_fail": 0}
for i in range(10):
    try:
        start = time.time()
        result = call_llm_json(messages=msgs, model=model, temperature=0.85, max_tokens=200)
        elapsed = time.time() - start
        data = result.get("data", {})
        comment = data.get("comment", "")
        if comment and len(comment.split()) >= 3:
            ok += 1
            words = len(comment.split())
            first = comment.split()[0].lower()
            em = "\u2014" in comment
            th = first in ("the", "this", "that", "there", "they")
            ing = first.endswith("ing")
            flags = ""
            if th: flags += "/TH"; violations["th"] += 1
            if ing: flags += "/ING"; violations["ing"] += 1
            if em: flags += "/EM"; violations["em"] += 1
            print(f"  {i+1}. [{words}w{flags}] ({elapsed:.1f}s) {comment[:100]}")
        else:
            violations["json_fail"] += 1
            print(f"  {i+1}. EMPTY ({elapsed:.1f}s)")
    except Exception as e:
        violations["json_fail"] += 1
        print(f"  {i+1}. ERROR: {str(e)[:80]}")

print(f"\n{'='*60}")
print(f"RESULTS: {model}")
print(f"{'='*60}")
print(f"Success: {ok}/10 ({100*ok//10}%)")
print(f"Violations: {violations}")
print(f"Quality: {'EXCELLENT' if ok >= 9 and sum(violations.values()) <= 1 else 'NEEDS WORK'}")

db.close()
