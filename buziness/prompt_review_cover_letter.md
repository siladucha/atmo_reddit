Hey Tzvi,

Sharing something important — the full inventory of AI prompts that drive everything RAMP produces.

Doc: https://docs.google.com/document/d/1RseeL2iUOs3w3O2jtIsasaMBATPkc4itQvGWRgTu0Fo/edit?tab=t.0#heading=h.chx5exkgv9us

---

**Why now:**

Every comment, every post, every strategy recommendation — it all comes from these prompts. They're the engine behind output quality. Right now they work, but they were written for speed during development. I haven't had business-side eyes on them.

You're the one talking to clients, seeing their reactions, hearing what resonates and what doesn't. I need that perspective baked into the prompts themselves.

---

**What's in the doc:**

- Full text of every AI prompt in the system (12 core + 8 onboarding)
- What each one does and where it sits in the pipeline
- Which ones produce content that goes directly on Reddit vs internal-only
- 27 questions where I need your input

---

**What I need from you (priority order):**

**This week — 20 min read:**
1. Section 1 (Comment Writer) — this is THE prompt. Everything an avatar writes on Reddit comes from here. Is the voice right? The length? The approach types?
2. Section 3 (Scoring) — this decides WHICH threads we engage with. Wrong scoring = great comments on irrelevant threads.

**When you have time:**
3. Section 5 (Post Generation) — new capability, not fully live yet. Want your take before we activate.
4. Sections 7-8 (Strategy) — should clients see/approve their avatar strategy? Or keep it internal?

---

**The key tension I want you to think about:**

Right now the default voice is "cynical, experienced practitioner who types fast and never writes essays." That works great for r/sysadmin and r/devops. But is it right for every client? A wellness brand? An education company?

The system supports per-client voice profiles that override the default — but the underlying personality ("be sharp, be short, plant seeds") stays constant. Should it?

---

**How your feedback translates to action:**

- "Comments are too short" → I adjust word limits in the prompt
- "We need a 'helpful answer' mode for help_seeking threads" → I add a new approach type
- "The scoring is too aggressive, we're engaging with angry threads" → I adjust thresholds
- "Clients want to see the strategy" → I build a client-facing strategy page

Every change is a 5-minute code deploy once we agree on direction.

---

Don't need you to read the whole thing cover-to-cover. Start with Section 1, tell me what feels off. We iterate from there.

Max
