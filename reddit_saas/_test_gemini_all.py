"""Exhaustive Gemini test: all models × all response formats.

Goal: find a Gemini combination that gives 100% reliability for hobby comments.
"""
import sys
sys.path.insert(0, '/app')

import litellm
import json
import time

# Models to test
MODELS = [
    "gemini/gemini-2.5-flash",
    "gemini/gemini-2.5-flash-lite",
]

# Response format approaches
APPROACHES = {
    "json_mode": {
        "response_format": {"type": "json_object"},
        "system_suffix": '\n\nReturn JSON: {"comment": "your text"}',
        "parse": "json",
    },
    "plain_text": {
        "response_format": None,
        "system_suffix": "\n\nReply with ONLY the comment text. Nothing else. No JSON. No quotes. No labels.",
        "parse": "text",
    },
    "plain_text_v2": {
        "response_format": None,
        "system_suffix": "\n\nYour entire response must be the comment itself — no wrappers, no explanation, no markdown.",
        "parse": "text",
    },
    "json_no_mode": {
        "response_format": None,
        "system_suffix": '\n\nRespond with exactly this JSON format and nothing else: {"comment": "your text here"}',
        "parse": "json_manual",
    },
}

SYSTEM_BASE = """You are a casual Reddit commenter. Generate a short comment (15-40 words).
Sound like a real person on their phone. One paragraph. No em-dashes. No "The/This/That" starters."""

USER = """Subreddit: r/productivity
Post title: How do you stay focused when working from home?
Post body: I've been WFH for 2 years and still struggle with distractions. My biggest enemy is my phone and random YouTube rabbit holes.
Upvotes: 47
Top comments: "Pomodoro changed my life" (12 ups), "I put my phone in another room" (8 ups)"""

N = 5  # calls per combination

print("=" * 80)
print("GEMINI EXHAUSTIVE TEST: models × response formats × 5 calls each")
print("=" * 80)

results_summary = []

for model in MODELS:
    for approach_name, approach in APPROACHES.items():
        system = SYSTEM_BASE + approach["system_suffix"]
        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": USER},
        ]
        
        kwargs = {
            "model": model,
            "messages": msgs,
            "max_tokens": 200,
            "temperature": 0.85,
        }
        if approach["response_format"]:
            kwargs["response_format"] = approach["response_format"]
        
        successes = 0
        violations = 0
        errors = 0
        times = []
        
        print(f"\n--- {model} + {approach_name} ---")
        
        for i in range(N):
            try:
                start = time.time()
                r = litellm.completion(**kwargs)
                elapsed = time.time() - start
                times.append(elapsed)
                
                raw = (r.choices[0].message.content or "").strip()
                
                # Parse based on approach
                comment = ""
                parse_ok = False
                
                if approach["parse"] == "json":
                    # Standard json_object mode
                    try:
                        data = json.loads(raw)
                        comment = data.get("comment", "")
                        parse_ok = bool(comment)
                    except json.JSONDecodeError:
                        # Try stripping markdown
                        cleaned = raw
                        if "```" in cleaned:
                            parts = cleaned.split("```")
                            for p in parts:
                                p = p.strip().removeprefix("json").strip()
                                try:
                                    data = json.loads(p)
                                    comment = data.get("comment", "")
                                    parse_ok = bool(comment)
                                    break
                                except:
                                    pass
                        if not parse_ok:
                            # Try finding { }
                            start_b = raw.find("{")
                            end_b = raw.rfind("}")
                            if start_b != -1 and end_b != -1:
                                try:
                                    data = json.loads(raw[start_b:end_b+1])
                                    comment = data.get("comment", "")
                                    parse_ok = bool(comment)
                                except:
                                    pass
                
                elif approach["parse"] == "text":
                    # Plain text — the response IS the comment
                    comment = raw
                    # Strip quotes
                    if comment.startswith('"') and comment.endswith('"'):
                        comment = comment[1:-1]
                    # Strip JSON wrapper if model still returned it
                    if comment.startswith("{"):
                        try:
                            data = json.loads(comment)
                            comment = data.get("comment", comment)
                        except:
                            comment = ""  # garbage
                    parse_ok = bool(comment) and len(comment.split()) >= 3
                
                elif approach["parse"] == "json_manual":
                    # No response_format but asked for JSON in prompt
                    cleaned = raw
                    if "```" in cleaned:
                        parts = cleaned.split("```")
                        for p in parts:
                            p = p.strip().removeprefix("json").strip()
                            try:
                                data = json.loads(p)
                                comment = data.get("comment", "")
                                parse_ok = bool(comment)
                                break
                            except:
                                pass
                    if not parse_ok:
                        start_b = raw.find("{")
                        end_b = raw.rfind("}")
                        if start_b != -1 and end_b != -1:
                            try:
                                data = json.loads(raw[start_b:end_b+1])
                                comment = data.get("comment", "")
                                parse_ok = bool(comment)
                            except:
                                pass
                    if not parse_ok:
                        # Maybe it just returned plain text
                        comment = raw
                        parse_ok = bool(comment) and len(comment.split()) >= 3 and not comment.startswith("{")
                
                if parse_ok and comment:
                    words = len(comment.split())
                    first = comment.split()[0].lower()
                    has_em = "\u2014" in comment
                    has_th = first in ("the", "this", "that", "there", "they")
                    has_ing = first.endswith("ing")
                    
                    if has_em or has_th or has_ing or words < 5:
                        violations += 1
                        flag = ""
                        if has_th: flag += "TH "
                        if has_ing: flag += "ING "
                        if has_em: flag += "EM "
                        print(f"  {i+1}. VIOLATION [{flag}] ({elapsed:.1f}s) {comment[:80]}")
                    else:
                        successes += 1
                        print(f"  {i+1}. OK [{words}w] ({elapsed:.1f}s) {comment[:80]}")
                else:
                    errors += 1
                    print(f"  {i+1}. PARSE_FAIL ({elapsed:.1f}s) raw={raw[:60]}")
                    
            except Exception as e:
                errors += 1
                print(f"  {i+1}. ERROR: {str(e)[:60]}")
        
        avg_t = sum(times) / len(times) if times else 0
        score = f"{successes}/{N}"
        results_summary.append((model, approach_name, successes, violations, errors, avg_t))
        print(f"  => {score} ok, {violations} violations, {errors} errors, avg {avg_t:.1f}s")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"{'Model':<30} {'Approach':<18} {'OK':>3} {'Viol':>4} {'Err':>4} {'Avg':>5}")
print("-" * 80)
for model, approach, ok, viol, err, avg_t in results_summary:
    marker = " ✅" if ok == N and viol == 0 else ""
    print(f"{model:<30} {approach:<18} {ok:>3} {viol:>4} {err:>4} {avg_t:>4.1f}s{marker}")
