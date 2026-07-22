---
inclusion: manual
---

# Product Expansion — Two New Verticals (July 12, 2026)

## Status: CONCEPT (Tzvi's Business Brief v4)

**Source:** Reddit_Avatar_Army_Business_Brief (4).docx — updated July 12, 2026.
**Decision:** Architecture orientation only. NOT for immediate implementation.
**Trigger for revisiting:** First paying client stable for 30+ days AND Tzvi confirms sales demand.

---

## 1. Community Hub — Client-Owned Subreddit Management

### What It Is

Managed service for clients who own (or want to create) a branded subreddit. RAMP avatars become the community's active members — seeding discussions, responding to posts, maintaining engagement, and moderating content.

### How It Differs From Current System

| Current RAMP | Community Hub |
|-------------|---------------|
| Avatars participate in OTHER people's subs | Avatars participate in CLIENT'S OWN sub |
| Goal: brand mentions in external discussions | Goal: active community that attracts organic members |
| Content strategy: blend in, add value contextually | Content strategy: seed topics, spark discussions, welcome newcomers |
| Success metric: karma, visibility, AEO citations | Success metric: sub growth (members, DAU), organic post ratio, engagement rate |
| Risk model: avatar ban = lost engagement opportunity | Risk model: if community dies = client asset lost |

### Architectural Impact (When We Build It)

| Component | Change Needed | Effort |
|-----------|--------------|--------|
| Avatar role model | New role: "community_seed" (posts discussion starters, not just comments) | S |
| EPG Pipeline | New slot type: "community_post" (original posts, not responses to existing threads) | M |
| Content generation | New prompt mode: topic seeding, discussion questions, community announcements | M |
| Metrics | New KPIs: sub member growth, organic-to-seeded ratio, average comments/post | S |
| Moderation layer | AutoMod config generation, rule enforcement, spam filtering | L |
| Scraping | Inward scraping of client's own sub (vs outward in external subs) | S |
| Strategy engine | Community growth strategy vs engagement strategy — different playbook | M |
| Client portal | Sub health dashboard (growth curve, engagement heatmap, top contributors) | M |

### What's Already Usable (Zero Build)

- Avatar management (same avatars can post in client's sub)
- Content generation engine (prompts can be adapted)
- Scheduling/EPG (timing engine works for any post)
- Safety gates (same phase system, karma still matters for credibility)
- Draft review flow (human approves community posts same as comments)

### Risks & Considerations

- Reddit may scrutinize new subs with high early engagement from linked accounts
- "Seeded" communities that never attract organic users are expensive vanity projects
- Moderation responsibility shifts to us (legal: client must be listed as mod, not RAMP)
- ROI harder to prove than external engagement (no direct AEO signal)

### v3.0 Alignment

Maps to: Content Graph (community posts = nodes), Community Intelligence (standalone value from sub analytics).

---

## 2. Voice Intelligence — Reddit Discussions → Multi-Channel Content

### What It Is

Transform high-value Reddit discussions (where avatars participate or that are scraped) into content assets for other marketing channels: LinkedIn posts, blog articles, email newsletters, social media snippets, sales enablement materials.

### How It Differs From Current System

| Current RAMP | Voice Intelligence |
|-------------|-------------------|
| Reddit is the output channel | Reddit is the INPUT source |
| Generate content FOR Reddit | Generate content FROM Reddit |
| Avatar is the actor | AI pipeline is the actor (no avatar needed) |
| Success: karma, visibility on Reddit | Success: content volume, engagement on OTHER platforms |
| One-way: strategy → Reddit comment | Two-way: Reddit insight → multi-channel asset |

### Architectural Impact (When We Build It)

| Component | Change Needed | Effort |
|-----------|--------------|--------|
| Content extraction pipeline | New: identify high-signal discussions (trending, pain points, questions) | M |
| Repurposing engine | New: LLM transforms Reddit thread context into format X (LinkedIn, blog, email) | M |
| Output formats | Templates for: LinkedIn post, blog intro, newsletter snippet, tweet thread, sales talking point | M |
| Source attribution | Track which Reddit thread/discussion inspired which content piece | S |
| Client portal | "Content Library" page — generated assets, download, copy, schedule | M |
| Delivery | Integration options: copy-paste (MVP), API, Zapier webhook, direct LinkedIn posting | S-L |
| Quality gate | Human review before publish (same P5 principle as Reddit drafts) | S |
| Metrics | Content pieces generated, used by client, engagement on destination platform (if trackable) | M |

### What's Already Usable (Zero Build)

- Reddit scraping pipeline (already collecting discussions)
- Thread scoring (already identifying high-value content)
- LLM generation infrastructure (same call_llm / cost tracking)
- Client strategy context (knows what topics matter to client)
- Draft review flow (human approval before delivery)
- Discovery Engine (already extracts insights from Reddit)

### Content Transformation Examples

| Reddit Source | Output Format | Example |
|--------------|---------------|---------|
| Popular thread with pain point | LinkedIn thought leadership post | "I keep seeing CISOs ask about X on Reddit. Here's what the community consensus is..." |
| Q&A where avatar gave expert answer | Blog post (expanded) | "The question came up: how do you handle Y? Here's the full breakdown..." |
| Trending topic in niche | Email newsletter item | "This week in [niche]: the community is buzzing about Z. Here's what it means for you." |
| Multiple threads with same theme | Sales deck talking point | "Reddit professionals mention [problem] 3x more than last quarter." |
| Thread with social proof (avatar upvoted) | Social proof snippet | "Community validated: our approach to X got 47 upvotes from IT professionals." |

### Risks & Considerations

- Content must NOT reveal RAMP's Reddit presence (never attribute to "our accounts")
- Attribution must be generic ("Reddit community" not "our avatar's post")
- Quality bar is different per channel (LinkedIn = polished, Twitter = punchy)
- Client may expect this to replace their content team (it supplements, not replaces)
- Measurement on external platforms requires client to share analytics (friction)

### v3.0 Alignment

Maps to: Community Intelligence (standalone value from Reddit data without engagement), Generation Router (repurposing uses cheaper models — Flash sufficient).

---

## Pricing Implications (Tzvi's Brief)

| Product | Likely Tier | Rationale |
|---------|------------|-----------|
| Community Hub | Add-on $500-1,000/mo per sub | Requires dedicated avatars + moderation + original content generation (higher LLM cost) |
| Voice Intelligence | Add-on $200-500/mo | Lower cost (extraction + repurposing via Flash), high perceived value |
| Bundle with existing engagement | Premium plan $1,499+ | Natural upsell for Growth/Scale clients |

---

## Implementation Priority (NOT NOW)

| Priority | When | Trigger |
|----------|------|---------|
| Voice Intelligence | After 3 paying clients | Lower lift, uses existing scraping/scoring. Tzvi can sell as "bonus insight" to close deals |
| Community Hub | After 5 paying clients | Higher lift, new operational model (moderation). Needs proven engagement quality first |

---

## What IS OK To Do Now (Architecture-Compatible Choices)

1. ✅ When scraping — already store full thread context (sufficient for Voice Intelligence extraction later)
2. ✅ When scoring — keep "insight_potential" as a mental model for future extraction value
3. ✅ When building Discovery reports — they're already proto-Voice Intelligence (insight extraction from Reddit)
4. ✅ When planning data model changes — keep post/comment content accessible (no aggressive TTL that deletes content needed for repurposing)
5. ✅ When Tzvi pitches — these are "roadmap items" not "available now"

## What NOT To Do Before Trigger

1. ❌ Build moderation tools speculatively
2. ❌ Build LinkedIn/Twitter integration before client asks
3. ❌ Create new content generation prompts for repurposing without demand signal
4. ❌ Promise delivery timelines to clients
5. ❌ Design new DB models for community management

---

## For Tzvi (Sales Positioning)

- Community Hub: "We don't just participate in communities — we can BUILD and MANAGE your branded community on Reddit. Same quality, your owned asset."
- Voice Intelligence: "Every Reddit discussion your avatars participate in generates intelligence. We can transform that into LinkedIn posts, blog content, and sales insights — multiplying the value of your Reddit investment across all channels."
- Both: "These aren't separate products. They're natural extensions of the engagement engine you're already paying for."

---

## Related Documentation

- `.kiro/steering/competitive_landscape.md` — market positioning context
- `.kiro/steering/v3_north_star.md` — long-term architecture (Community Intelligence = Voice Intelligence precursor)
- `.kiro/specs/ai-native-expert-warming/` — authority building feeds into Voice Intelligence sourcing
- `docs/Reddit_Avatar_Army_Business_Brief.docx` — Tzvi's original brief (v3)
- `buziness/` — client-facing materials
