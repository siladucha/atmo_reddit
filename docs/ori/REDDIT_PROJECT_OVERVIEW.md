# Reddit Engagement Project — System Overview (Ori, ~Feb 2026)

> Saved from Ori handoff materials. Describes the n8n+Supabase+Airtable architecture
> that RAMP fully replaced. Kept for strategic framing and prompt design reference.

## Key Extractions for RAMP

### The 99/1 Rule (useful for client communication)
- 99% of comments: genuinely helpful, build karma, push worldview only when natural
- 1% of comments: brand mention (only when explicitly asked for, competitor mentioned, or perfect fit)

### Four Pillars (all implemented in RAMP)
1. Scraping & Filtering → RAMP: queue_tick + smart_scoring
2. Strategic Commenting → RAMP: generation + EPG + review
3. Hobby & Karma Building → RAMP: hobby pipeline + Phase 0-1
4. Content Creation & Posting → RAMP: post_generation (partial)

### Persona Selection Logic (validates RAMP approach)
- Subreddit eligibility
- Audience match (peer credibility)
- Topic fit
- Karma level for priority threads
- Engagement modes: bullseye / helpful_peer / karma_only

### Comment Quality Standard (5 tests)
1. Originality — says something new
2. Voice fidelity — persona would actually say this
3. Value — reader learns something
4. Specificity — can't work on 10 different posts
5. Human test — sounds like phone typing, not polished content

### Anti-Detection Philosophy (3 threats)
1. Reddit community detection (humans spotting shills)
2. Reddit platform detection (algorithmic flagging)
3. AI-sounding content (buzzword/polish detection)

## Full Document

[See original PDF/attachment in Tzvi's email for complete text]
