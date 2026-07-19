"""Test via RAMP's call_llm_json which handles keys and parsing."""
import sys
sys.path.insert(0, '/app')

from app.services.ai import call_llm_json
from app.database import SessionLocal
import time

db = SessionLocal()

system = """You are a casual Reddit commenter. Generate ONE short comment (15-40 words).
Return ONLY a JSON object: {"comment": "your text here"}
No markdown. No code blocks. No explanation. Just raw JSON."""

user = """Subreddit: r/productivity
Post title: How do you stay focused when working from home?
Post body: I've been WFH for 2 years and still struggle with distractions.
Upvotes: 47

Return: {"comment": "..."}"""

msgs = [
    {"role": "system", "content": system},
    {"role": "user", "content": user},
]

# Test gemini-2.5-flash via call_llm_json (with RAMP's _extract_json + retry)
print("=== Testing via RAMP call_llm_json ===\n")

models = [
    ("gemini/gemini-2.5-flash", 10),
]

for model, n in models:
    print(f"--- {model} ({n} calls) ---")
    ok = 0
    fail_reasons = []
    for i in range(n):
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
                if th: flags += "/TH"
                if ing: flags += "/ING"  
                if em: flags += "/EM"
                print(f"  {i+1}. OK [{words}w{flags}] ({elapsed:.1f}s) {comment[:90]}")
            else:
                fail_reasons.append("empty_comment")
                print(f"  {i+1}. EMPTY ({elapsed:.1f}s) data={data}")
        except Exception as e:
            fail_reasons.append(str(e)[:40])
            print(f"  {i+1}. ERROR: {str(e)[:80]}")
    
    print(f"\n  SCORE: {ok}/{n} success ({100*ok//n}%)")
    if fail_reasons:
        print(f"  Failures: {fail_reasons[:3]}")
    print()

db.close()
