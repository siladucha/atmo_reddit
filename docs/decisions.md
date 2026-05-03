# Decisions & Open Questions

## What's Clear ✅

### Documentation — Excellent
- Full database schema with 10 tables documented
- All 9 n8n workflows provided as JSON exports
- Airtable structure documented (interfaces + automation)
- Step-by-step setup guide with exact order
- 3 specific migration fixes documented with SQL
- Credential checklist provided
- Workflow architecture diagram (what calls what)
- Data flow diagram (end-to-end)

### Data — Complete
- 7 CSV files for Airtable seeding
- Keywords list with probability levels and categories
- 7 Reddit personas fully defined (voice profiles, constraints, vocabulary)
- Sample comments and posts with full metadata
- Reddit post drafts with strategic briefs

### Strategy — Well Documented
- Comment strategy: Paradigm Shift → Helpful → Karma Play fallback
- Avatar assignment logic: "Who would be least annoying to the audience?"
- Human-in-the-loop: All posting is manual (deliberate anti-ban measure)
- Hobby karma building pipeline for avatar authenticity
- Refined Version field for human feedback loop

---

## What Needs Decisions 🔶

### 1. Accounts to Open
**Need partner's company accounts for:**
- [ ] Supabase account (free tier works for start)
- [ ] n8n instance (cloud at ~$20/mo OR self-hosted)
- [ ] Airtable account (free tier may work initially)
- [ ] OpenRouter account (pay-per-use LLM access)
- [ ] Reddit API app (free, needs a Reddit account)
- [ ] Pushover (optional, $5 one-time per platform)

### 2. Reddit Scraper Method
Original Reddit API app is unavailable. Three options:
- **Option A:** Create own Reddit App at reddit.com/prefs/apps (free, recommended)
- **Option B:** Use RapidAPI "Reddit Unofficial" (paid, simpler)
- **Option C:** Use Reddit RSS feeds (free, limited data)
**Recommendation:** Option A — it's free and gives full API access

### 3. n8n Hosting
- **Cloud (n8n.io):** Easier, ~$20/mo, managed
- **Self-hosted:** Free, needs a server (Docker), more control
**Recommendation:** Start with n8n cloud for speed, migrate to self-hosted later if needed

### 4. LLM Provider
- System uses OpenRouter as a router to access multiple LLMs
- Gemini Flash for cheap qualification/filtering
- Claude/GPT for high-quality comment writing
**Cost estimate:** ~$30-50/month at moderate volume

---

## What's Missing / Unclear 🔴

### 1. No `news_scrape` Data Source
- The Post Creation workflow reads from `news_scrape` table
- Fix 2 redirects it to `reddit_threads`, but this changes the post creation logic
- **Question:** Where does news content come from? Was there a separate news scraping workflow not included?
- **Impact:** Post creation pipeline may need rethinking

### 2. Sub-workflow IDs Need Updating
- All "Execute Workflow" nodes reference old workflow IDs from Ori's n8n instance
- These MUST be updated after import to point to new workflow IDs
- This is documented but easy to miss

### 3. Airtable Base/Table IDs
- All workflows reference `appBJpoCIlUHEYi5J` (Ori's Airtable base)
- Every Airtable node in every workflow needs new IDs after setup
- This is a significant manual effort across 9 workflows

### 4. Client ID Hardcoded
- `1PFMSu` is hardcoded in multiple SQL queries
- Need to create this exact ID in the new `clients` table, or update all references

### 5. Credential Mapping
- Reddit OAuth2 credentials for scraping
- Reddit avatar account credentials (stored in `reddit_avatars` table — sensitive!)
- PostgreSQL connection strings
- Airtable API token
- OpenRouter API key
- Pushover API key + user key

### 6. No Automated Posting
- All Reddit posting is manual (human copies text, logs into avatar account, posts)
- This is intentional for safety but means significant daily human effort
- **Question:** Is there a plan to semi-automate this later?

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Reddit avatar accounts get banned | HIGH | Hobby karma pipeline, manual posting, human review |
| LLM costs spike unexpectedly | MEDIUM | Use Gemini Flash for filtering, set OpenRouter budget limits |
| Airtable free tier limits hit | MEDIUM | Monitor record counts, upgrade if needed |
| Reddit API rate limits | LOW | Scrape entire subreddits (not keyword-based), respect rate limits |
| n8n workflow breaks after import | MEDIUM | Test each workflow individually per setup guide |
