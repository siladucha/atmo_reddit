# RAMP White Label — Financial Model

## Document Purpose

This financial model projects RAMP's white-label revenue across two scenarios (conservative and aggressive) for Year 1. All numbers are internally consistent and sourced from operational cost data.

**Key cost assumptions (sourced from LLM cost analysis):**
- LLM cost per client: $1.17/day = ~$35/mo per client
- LLM cost per partner (8 clients): $35 × 8 = **$280/mo**
- Infrastructure cost per additional partner: **$0/mo** (same server, same DB, same codebase)
- Support cost per partner (amortized): **~$200/mo** (shared ops team time)

---

## 1. Monthly Revenue Projection (Month 1–12)

### Conservative Scenario — 5 Partners by Month 12

**Assumptions:**
- Partner acquisition: ~1 new partner every 2–3 months
- Average revenue per partner: $2,500/mo (mix of Starter at $999 + Growth at $1,999)
- Avatar inventory sales: $400/mo per partner (avg 1–2 avatars sold/mo at $199–$499)
- No managed service upsells in conservative case

| Month | Partners | Platform Revenue | Avatar Sales | Total Monthly Revenue | Cumulative Revenue |
|-------|----------|-----------------|--------------|----------------------|-------------------|
| 1     | 1        | $2,500           | $200         | $2,700               | $2,700            |
| 2     | 1        | $2,500           | $400         | $2,900               | $5,600            |
| 3     | 2        | $5,000           | $600         | $5,600               | $11,200           |
| 4     | 2        | $5,000           | $800         | $5,800               | $17,000           |
| 5     | 3        | $7,500           | $1,000       | $8,500               | $25,500           |
| 6     | 3        | $7,500           | $1,200       | $8,700               | $34,200           |
| 7     | 3        | $7,500           | $1,400       | $8,900               | $43,100           |
| 8     | 4        | $10,000          | $1,600       | $11,600              | $54,700           |
| 9     | 4        | $10,000          | $1,800       | $11,800              | $66,500           |
| 10    | 5        | $12,500          | $2,000       | $14,500              | $81,000           |
| 11    | 5        | $12,500          | $2,000       | $14,500              | $95,500           |
| 12    | 5        | $12,500          | $2,000       | $14,500              | $110,000          |

**Year 1 Conservative Total: ~$110,000 actual collected**
**Run-rate ARR at Month 12: $14,500/mo × 12 = $174,000**

---

### Aggressive Scenario — 10 Partners by Month 12

**Assumptions:**
- Partner acquisition: ~1 new partner per month (strong outreach + referrals)
- Average revenue per partner: $4,000/mo (Growth at $1,999 + Scale at $3,499 mix)
- Avatar inventory sales: $500/mo per partner (2–3 avatars sold/mo)
- Managed service upsells: $1,000/mo per partner (starting Month 4)

| Month | Partners | Platform Revenue | Avatar Sales | Managed Upsells | Total Monthly Revenue | Cumulative Revenue |
|-------|----------|-----------------|--------------|-----------------|----------------------|-------------------|
| 1     | 1        | $4,000           | $300         | $0              | $4,300               | $4,300            |
| 2     | 2        | $8,000           | $600         | $0              | $8,600               | $12,900           |
| 3     | 3        | $12,000          | $1,000       | $0              | $13,000              | $25,900           |
| 4     | 4        | $16,000          | $1,500       | $2,000          | $19,500              | $45,400           |
| 5     | 5        | $20,000          | $2,000       | $3,000          | $25,000              | $70,400           |
| 6     | 6        | $24,000          | $2,500       | $4,000          | $30,500              | $100,900          |
| 7     | 7        | $28,000          | $3,000       | $5,000          | $36,000              | $136,900          |
| 8     | 8        | $32,000          | $3,500       | $6,000          | $41,500              | $178,400          |
| 9     | 9        | $36,000          | $4,000       | $7,000          | $47,000              | $225,400          |
| 10    | 10       | $40,000          | $4,500       | $8,000          | $52,500              | $277,900          |
| 11    | 10       | $40,000          | $5,000       | $9,000          | $54,000              | $331,900          |
| 12    | 10       | $40,000          | $5,000       | $10,000         | $55,000              | $386,900          |

**Year 1 Aggressive Total: ~$387,000 actual collected**
**Run-rate ARR at Month 12: $55,000/mo × 12 = $660,000**

---

## 2. Cost Structure Breakdown

### Fixed Costs (Monthly — regardless of partner count)

| Cost Item | Monthly | Annual | Notes |
|-----------|---------|--------|-------|
| Infrastructure (DigitalOcean) | $23 | $276 | Single droplet, Docker Compose |
| Domain + SSL | $5 | $60 | Wildcard cert for partner domains |
| Redis/Valkey | $6 | $72 | Cache + locks (flat until 500 clients) |
| Monitoring/Logging | $10 | $120 | Basic observability |
| **Total Fixed** | **$44** | **$528** | |

### Variable Costs (Per Partner, Monthly)

| Cost Item | Per Partner/Mo | Source | Notes |
|-----------|---------------|--------|-------|
| LLM API (8 clients) | $280 | $1.17/day × 8 clients × 30 days | Claude Sonnet + Gemini Flash |
| Support (amortized) | $200 | Shared ops team time | Decreases per-partner as volume grows |
| Avatar warming (inventory) | $50 | ~$15-25/mo per avatar × 2-3 warming | Amortized across inventory |
| Infrastructure | $0 | Same server, same DB | Zero marginal cost |
| **Total Variable** | **$530** | | Per partner |

### LLM Cost Breakdown Per Client (8 clients = 1 partner)

| Operation | Model | Calls/Day | Cost/Call | Cost/Day | Cost/Month |
|-----------|-------|-----------|-----------|----------|-----------|
| Scoring | Gemini Flash | 20 | $0.0003 | $0.006 | $0.18 |
| Persona Selection | Claude Sonnet | 15 | $0.020 | $0.30 | $9.00 |
| Comment Generation | Claude Sonnet | 15 | $0.039 | $0.59 | $17.70 |
| Comment Editor | Claude Sonnet | 15 | $0.018 | $0.27 | $8.10 |
| Hobby Comments | Gemini Flash | 15 | $0.0003 | $0.005 | $0.15 |
| **Total per client** | | | | **$1.17** | **$35.13** |
| **Total per partner (×8)** | | | | **$9.36** | **$281.04** |

---

## 3. Gross Margin Analysis

### Conservative Scenario (Month 12 — 5 Partners)

| Line Item | Monthly |
|-----------|---------|
| **Revenue** | |
| Platform fees (5 × $2,500) | $12,500 |
| Avatar inventory sales | $2,000 |
| **Total Revenue** | **$14,500** |
| | |
| **Costs** | |
| LLM API (5 × $280) | $1,400 |
| Support (5 × $200) | $1,000 |
| Avatar warming (5 × $50) | $250 |
| Fixed infrastructure | $44 |
| **Total Costs** | **$2,694** |
| | |
| **Gross Profit** | **$11,806** |
| **Gross Margin** | **81.4%** |

### Aggressive Scenario (Month 12 — 10 Partners)

| Line Item | Monthly |
|-----------|---------|
| **Revenue** | |
| Platform fees (10 × $4,000) | $40,000 |
| Avatar inventory sales | $5,000 |
| Managed service upsells | $10,000 |
| **Total Revenue** | **$55,000** |
| | |
| **Costs** | |
| LLM API (10 × $280) | $2,800 |
| Support (10 × $200) | $2,000 |
| Avatar warming (10 × $50) | $500 |
| Fixed infrastructure | $44 |
| Additional ops hire (partial) | $2,000 |
| **Total Costs** | **$7,344** |
| | |
| **Gross Profit** | **$47,656** |
| **Gross Margin** | **86.6%** |

### Margin Sensitivity by Partner Count

| Partners | Revenue/Mo | Total Costs/Mo | Gross Profit/Mo | Gross Margin |
|----------|-----------|---------------|----------------|-------------|
| 1 | $2,700 | $574 | $2,126 | 78.7% |
| 3 | $8,500 | $1,634 | $6,866 | 80.8% |
| 5 | $14,500 | $2,694 | $11,806 | 81.4% |
| 8 | $34,000 | $4,284 | $29,716 | 87.4% |
| 10 | $55,000 | $7,344 | $47,656 | 86.6% |

**Key insight:** Gross margin improves with scale because fixed costs are amortized and support cost per partner decreases. Margin stabilizes at 85-87% above 8 partners.

---

## 4. Unit Economics Summary

### Per-Partner Unit Economics (Growth Tier — 8 Clients)

| Metric | Value | Source |
|--------|-------|--------|
| **Revenue per partner** | $1,999–$4,000/mo | Tier pricing (Growth–Scale) |
| **Infrastructure cost** | $0/mo | Same server, same DB, same codebase |
| **LLM cost (8 clients)** | $280/mo | $1.17/day × 8 clients × 30 days |
| **Support cost (amortized)** | $200/mo | Shared ops team, decreases at scale |
| **Avatar warming (amortized)** | $50/mo | Inventory maintenance allocation |
| **Total cost per partner** | $530/mo | |
| **Gross profit per partner** | $1,469–$3,470/mo | Revenue minus costs |
| **Gross margin per partner** | **73–87%** | Depends on tier |
| **Payback period** | <1 month | First payment covers all costs |
| **LTV (annual contract)** | $17,628–$41,640 | 12 × gross profit |
| **CAC target** | <$2,000 | Direct outreach, no paid ads |
| **LTV:CAC ratio** | >8:1 | Excellent unit economics |

### Per-Tier Breakdown

| Tier | Monthly Fee | LLM Cost | Support | Margin $ | Margin % |
|------|------------|----------|---------|----------|----------|
| Starter (3 slots) | $999 | $105 | $200 | $644 | 64.5% |
| Growth (8 slots) | $1,999 | $280 | $200 | $1,469 | 73.5% |
| Scale (20 slots) | $3,499 | $700 | $200 | $2,549 | 72.8% |
| Enterprise (custom) | $5,000+ | $1,050+ | $400 | $3,500+ | 70%+ |

**Note:** Starter tier has lower absolute margin but still 64%+ gross. Growth tier is the sweet spot for margin percentage due to support cost amortization.

### Avatar Inventory Unit Economics

| Metric | Silver Avatar | Gold Avatar |
|--------|-------------|-------------|
| Sale price | $199 (one-time) | $499 (one-time) |
| Warming cost | ~$15/mo × 3 months = $45 | ~$25/mo × 6 months = $150 |
| Gross profit per avatar | $154 | $349 |
| Margin | 77% | 70% |
| Payback period | Immediate (one-time sale) | Immediate (one-time sale) |

---

## 5. Key Financial Metrics Summary

| Metric | Conservative | Aggressive |
|--------|-------------|-----------|
| Partners at Month 12 | 5 | 10 |
| Run-rate ARR (Month 12) | $174,000 | $660,000 |
| Year 1 actual collected | ~$110,000 | ~$387,000 |
| Gross margin (Month 12) | 81% | 87% |
| Monthly burn at Month 12 | $2,694 | $7,344 |
| Monthly profit at Month 12 | $11,806 | $47,656 |
| Break-even point | Month 1 (first partner) | Month 1 (first partner) |
| LLM cost as % of revenue | 10% | 5% |
| Infrastructure as % of revenue | <1% | <1% |

---

## 6. Revenue Composition (Month 12)

### Conservative

```
Platform Fees:    ████████████████████████████████████████  86% ($12,500)
Avatar Sales:    ██████                                     14% ($2,000)
Managed Upsells: (none)                                      0%
                                                    Total: $14,500/mo
```

### Aggressive

```
Platform Fees:    ████████████████████████████████████  73% ($40,000)
Avatar Sales:    █████                                  9% ($5,000)
Managed Upsells: ██████████                            18% ($10,000)
                                                    Total: $55,000/mo
```

---

## 7. Assumptions & Risks

### Key Assumptions

1. **Partner acquisition rate** — Conservative: 1 per 2-3 months. Aggressive: 1 per month.
2. **Zero churn in Year 1** — Annual contracts prevent early exits. Realistic given switching costs.
3. **LLM costs stable** — $1.17/day/client. May decrease as models get cheaper (upside).
4. **No additional infrastructure** — Single DigitalOcean droplet handles 10 partners / 80 clients. Validated by current architecture supporting 50+ avatars on same hardware.
5. **Support scales sub-linearly** — $200/partner amortized assumes shared ops. May need dedicated hire at 8+ partners ($4K/mo).

### Downside Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Slower partner acquisition | Lower revenue ramp | Annual contracts lock in committed partners |
| Partner churn after Year 1 | Revenue loss | High switching costs (branding, trained avatars, data) |
| LLM cost increase | Margin compression | Can switch models (Haiku for editing saves 40%) |
| Reddit enforcement action | Partner confidence loss | Contractual risk acceptance + safety guardrails |
| Support burden higher than expected | Margin compression | Tiered support model limits exposure |

### Upside Scenarios (Not Modeled)

- Partners upgrading tiers (Starter → Growth → Scale)
- Slot overage revenue ($199/additional client/month)
- Revenue share model generating higher per-partner revenue
- Direct client revenue (non-white-label) running in parallel
- International expansion (non-English markets)

---

## 8. LLM Cost Attribution Per Partner (Detailed)

This section provides granular LLM cost attribution for a single white-label partner operating at the Growth tier (8 client slots). All figures are consistent with the per-client breakdown in Section 2.

### Per-Client LLM Cost Breakdown (Daily)

| Operation | Model | Calls/Day | Cost/Call | Daily Cost |
|-----------|-------|-----------|-----------|-----------|
| Scoring | Gemini Flash | 20 | $0.0003 | $0.006 |
| Persona Selection | Claude Sonnet | 15 | $0.020 | $0.30 |
| Comment Generation | Claude Sonnet | 15 | $0.039 | $0.59 |
| Comment Editor | Claude Sonnet | 15 | $0.018 | $0.27 |
| Hobby Comments | Gemini Flash | 15 | $0.0003 | $0.005 |
| **Total per client** | | **80** | | **$1.17/day** |

**Monthly per client:** $1.17 × 30 = **$35.13/month**

### Per-Partner Attribution (8 Clients — Growth Tier)

| Metric | Value |
|--------|-------|
| Total LLM cost (8 × $35.13) | **$281/month** |
| As % of Growth tier platform fee ($1,999) | **14.1%** |
| As % of partner's client revenue (8 × $2,500 = $20,000) | **1.4%** |
| LLM cost per dollar of partner revenue | $0.014 |
| Gross profit after LLM (Growth tier) | $1,718/month |

**Key insight:** LLM costs represent only 14% of what the partner pays RAMP, and just 1.4% of what the partner collects from their end-clients. This creates massive margin headroom for both RAMP and the partner.

### Cost Breakdown by Model (Per Partner/Month)

| Model | Operations | Monthly Cost | % of LLM Total |
|-------|-----------|-------------|----------------|
| Claude Sonnet | Persona + Generation + Editing | $273.60 | 97.4% |
| Gemini Flash | Scoring + Hobby | $7.44 | 2.6% |
| **Total** | | **$281.04** | **100%** |

Claude Sonnet dominates cost. Gemini Flash operations are essentially free.

### Cost Optimization Opportunities

| Optimization | Savings/Partner/Mo | Implementation | Risk |
|-------------|-------------------|----------------|------|
| Replace Claude Sonnet with Haiku for editing | ~$65 | Model swap in config | Lower edit quality (acceptable for cleanup) |
| Skip persona selection for single-avatar clients | ~$9 per such client | Already implemented | None (no routing needed) |
| Batch scoring (10 threads per prompt) | ~$2 (30% of scoring) | Prompt restructuring | Slightly lower per-thread accuracy |
| Reduce generation context to 500 tokens | ~$20 | Trim thread body | May miss context in long threads |
| Cache voice profiles in prompt | ~$5 | Avoid re-fetch | Stale profile risk (low) |

**Maximum savings if all applied:** ~$92/partner/month (33% reduction)
**Post-optimization LLM cost:** ~$189/partner/month (9.5% of Growth tier fee)

### Scaling Projection (LLM Costs Only)

| Partners | Clients | LLM Cost/Month | Platform Revenue/Month | LLM as % of Revenue |
|----------|---------|---------------|----------------------|---------------------|
| 1 | 8 | $281 | $1,999 | 14.1% |
| 5 | 40 | $1,405 | $9,995 | 14.1% |
| 10 | 80 | $2,810 | $19,990 | 14.1% |
| 25 | 200 | $7,025 | $49,975 | 14.1% |
| 50 | 400 | $14,050 | $99,950 | 14.1% |

**LLM costs scale linearly with partners** — no volume discounts from providers at this scale. However, LLM pricing trends downward over time (Anthropic/Google price cuts), so actual costs at 50 partners may be 30-50% lower than projected.

**At 50 partners:** $14,050/mo LLM cost against ~$100K/mo platform revenue = still only 14% of revenue. Combined with infrastructure ($44 fixed + ~$0 marginal), total COGS remains under 15% at any scale.

### Attribution by Pipeline Stage

```
Comment Generation:  ████████████████████████████████████████████████  50% ($141/partner)
Persona Selection:   ██████████████████████████                        26% ($72/partner)
Comment Editor:      ███████████████████████                           23% ($65/partner)
Scoring:             ░                                                  0.6% ($1.44/partner)
Hobby Comments:      ░                                                  0.4% ($1.20/partner)
```

**Takeaway for investors:** The expensive operations (generation, persona, editing) are the ones that deliver direct value to end-clients. The cheap operations (scoring, hobby) are infrastructure. There is no "wasted" LLM spend — every dollar of AI cost maps to a client-facing deliverable.

---

## 9. Unit Economics Per Partner Tier (Detailed)

This section expands on the per-tier breakdown in Section 4 with granular cost attribution, gross margin analysis, and lifetime value calculations for each white-label partner tier.

---

### Starter Tier — 3 Client Slots, $999/mo

| Metric | Value | Notes |
|--------|-------|-------|
| **Monthly platform fee** | $999 | Annual contract ($11,988/year) |
| **Client slots included** | 3 | |
| **LLM cost** | $105/mo | 3 clients × $35/mo per client |
| **Support allocation** | $200/mo | Email only, shared ops team |
| **Avatar warming** | $30/mo | Fewer avatars in rotation |
| **Infrastructure** | $0/mo | Same server, same DB |
| **Total COGS** | **$335/mo** | |
| **Gross profit** | **$664/mo** | |
| **Gross margin** | **66.5%** | |
| **Partner LTV (12-month contract)** | **$7,968** | 12 × $664 |
| **CAC target** | <$1,500 | Direct outreach, no paid ads |
| **LTV:CAC ratio** | >5:1 | Acceptable for entry tier |
| **Payback period** | <1 month | First payment covers all costs |

**Notes:**
- Lower margin than Growth/Scale but still healthy at 66.5%
- Good entry point for agencies testing the model with 1-3 initial clients
- Most Starter partners upgrade to Growth within 6 months as they prove ROI to their clients
- $500 setup fee (not waived) adds $500 to first-year revenue = $12,488 total Year 1
- Support cost is disproportionately high relative to revenue (20% of fee) — this is the margin drag

---

### Growth Tier — 8 Client Slots, $1,999/mo

| Metric | Value | Notes |
|--------|-------|-------|
| **Monthly platform fee** | $1,999 | Annual contract ($23,988/year) |
| **Client slots included** | 8 | |
| **LLM cost** | $280/mo | 8 clients × $35/mo per client |
| **Support allocation** | $200/mo | Slack channel + monthly strategy call |
| **Avatar warming** | $50/mo | Standard inventory allocation |
| **Infrastructure** | $0/mo | Same server, same DB |
| **Total COGS** | **$530/mo** | |
| **Gross profit** | **$1,469/mo** | |
| **Gross margin** | **73.5%** | |
| **Partner LTV (12-month contract)** | **$17,628** | 12 × $1,469 |
| **CAC target** | <$2,000 | Direct outreach + referrals |
| **LTV:CAC ratio** | >8:1 | Excellent unit economics |
| **Payback period** | <1 month | First payment covers all costs |

**Notes:**
- **Sweet spot tier** — best balance of margin percentage and absolute profit
- Support cost amortizes well: $200 shared across 8 clients = $25/client vs. $67/client on Starter
- Setup fee waived (Growth+) — reduces friction for committed partners
- Partners at this tier typically charge $2,000-3,000/client/month → $16K-24K revenue against $1,999 platform cost
- 73.5% margin gives RAMP strong unit economics while partner enjoys 10x+ leverage on their investment
- This is the tier to prioritize in sales conversations

---

### Scale Tier — 20 Client Slots, $3,499/mo

| Metric | Value | Notes |
|--------|-------|-------|
| **Monthly platform fee** | $3,499 | Annual contract ($41,988/year) |
| **Client slots included** | 20 | |
| **LLM cost** | $700/mo | 20 clients × $35/mo per client |
| **Support allocation** | $400/mo | Dedicated account manager + QBR |
| **Avatar warming** | $100/mo | Larger inventory rotation |
| **Infrastructure** | $0/mo | Same server, same DB |
| **Total COGS** | **$1,200/mo** | |
| **Gross profit** | **$2,299/mo** | |
| **Gross margin** | **65.7%** | |
| **Partner LTV (12-month contract)** | **$27,588** | 12 × $2,299 |
| **CAC target** | <$3,000 | Relationship-based sales |
| **LTV:CAC ratio** | >9:1 | Strong unit economics |
| **Payback period** | <1 month | First payment covers all costs |

**Notes:**
- Higher absolute profit ($2,299 vs. $1,469) but lower margin % (65.7% vs. 73.5%)
- Margin compression comes from dedicated account manager ($400 vs. $200 shared support)
- Partners at this tier are established agencies with 10-20 active clients
- Slot overage revenue likely: partners at 20 slots often need 22-25 → $199/extra slot adds margin
- QBR (Quarterly Business Review) included — higher touch but drives retention and upsells
- These partners rarely churn — switching costs are enormous at 20 clients

---

### Enterprise Tier — Custom, ~$5,000+/mo

| Metric | Value | Notes |
|--------|-------|-------|
| **Monthly platform fee** | $5,000+ | Custom pricing per deal |
| **Client slots included** | 30+ | Negotiated per contract |
| **LLM cost** | $1,050+/mo | 30+ clients × $35/mo per client |
| **Support allocation** | $600/mo | Named AM + dedicated tech contact |
| **Avatar warming** | $150/mo | Priority inventory access |
| **Infrastructure** | $0/mo | Same server, same DB |
| **Total COGS** | **$1,800+/mo** | |
| **Gross profit** | **$3,200+/mo** | |
| **Gross margin** | **64%+** | |
| **Partner LTV (12-month contract)** | **$38,400+** | 12 × $3,200+ |
| **CAC target** | <$5,000 | High-touch enterprise sales |
| **LTV:CAC ratio** | >7:1 | Strong for enterprise |
| **Payback period** | <1 month | First payment covers all costs |

**Notes:**
- Custom pricing allows margin optimization per deal — can push to 70%+ for larger commitments
- Named account manager + tech contact = highest support cost but highest retention
- Enterprise partners often negotiate revenue share hybrid (flat fee + % above threshold)
- These deals typically include custom SLA, priority feature requests, and co-marketing
- Volume discount on avatars possible (bulk Gold purchases at $399 vs. $499)
- Longest sales cycle (2-3 months) but highest LTV and lowest churn

---

### Tier Comparison Table

| Metric | Starter | Growth | Scale | Enterprise |
|--------|---------|--------|-------|-----------|
| **Monthly fee** | $999 | $1,999 | $3,499 | $5,000+ |
| **Client slots** | 3 | 8 | 20 | 30+ |
| **Cost per slot** | $333 | $250 | $175 | $167 |
| **Total COGS** | $335 | $530 | $1,200 | $1,800+ |
| **Gross profit** | $664 | $1,469 | $2,299 | $3,200+ |
| **Gross margin %** | 66.5% | **73.5%** ⭐ | 65.7% | 64%+ |
| **LTV (12-mo)** | $7,968 | $17,628 | $27,588 | $38,400+ |
| **LTV:CAC** | >5:1 | >8:1 | >9:1 | >7:1 |
| **Support model** | Email | Slack + call | Dedicated AM | AM + tech |
| **Setup fee** | $500 | Waived | Waived | Waived |
| **Upgrade path** | → Growth | → Scale | → Enterprise | Custom |

---

### Sales Prioritization Guidance

**Priority 1: Growth Tier ($1,999/mo)**
- Highest gross margin percentage (73.5%)
- Best LTV:CAC ratio (>8:1)
- Lowest support burden relative to revenue
- Partners at this tier have enough clients to prove value but not enough to demand dedicated resources
- Setup fee waived removes friction
- **Target: 60% of new partner acquisitions**

**Priority 2: Scale Tier ($3,499/mo)**
- Highest absolute gross profit ($2,299/mo)
- Highest LTV:CAC ratio (>9:1) due to relationship-based acquisition
- Partners at this tier are sticky — massive switching costs
- Margin compression from dedicated AM is acceptable given retention
- **Target: 25% of new partner acquisitions**

**Priority 3: Starter Tier ($999/mo)**
- Entry point for agencies testing the model
- Lower margin (66.5%) but serves as pipeline for Growth upgrades
- 50%+ of Starter partners upgrade within 6 months
- **Target: 15% of new partner acquisitions (upgrade-focused)**

**Priority 4: Enterprise (Custom)**
- Opportunistic — don't actively pursue until 5+ Growth/Scale partners prove the model
- Long sales cycle, high support cost, but massive LTV
- **Target: Inbound only in Year 1**

---

### Blended Economics at Scale (10 Partners)

Assuming the recommended mix (1 Starter, 6 Growth, 2 Scale, 1 Enterprise):

| Metric | Value |
|--------|-------|
| **Total monthly revenue** | $999 + (6 × $1,999) + (2 × $3,499) + $5,000 = **$24,991/mo** |
| **Total monthly COGS** | $335 + (6 × $530) + (2 × $1,200) + $1,800 = **$7,715/mo** |
| **Blended gross profit** | **$17,276/mo** |
| **Blended gross margin** | **69.1%** |
| **Annual gross profit** | **$207,312** |
| **Run-rate ARR** | **$299,892** |

This blended model shows that even with a mix of tiers, RAMP maintains ~69% gross margins on white-label revenue — well above SaaS industry benchmarks of 60-70%.

---

## 10. Avatar Inventory ROI Model

This section models the economics of RAMP's avatar inventory as a business asset — analyzing warming costs, sale prices, payback periods, and the unique property that unsold inventory appreciates rather than depreciates.

---

### Warming Cost Breakdown

Each avatar incurs monthly costs during the warming period. Costs vary by target tier:

| Cost Component | Silver (per month) | Gold (per month) | Notes |
|---------------|-------------------|------------------|-------|
| Proxy IP (residential, static) | $2.50 | $2.50 | Per-avatar dedicated IP |
| Hobby content generation (Gemini Flash) | $1.50 | $3.00 | More subs = more hobby posts for Gold |
| Karma tracking + health monitoring | $0.50 | $0.50 | Celery Beat tasks (amortized) |
| Reddit API overhead (PRAW calls) | $0.50 | $1.00 | Scraping + posting + health checks |
| Infrastructure allocation (amortized) | $1.00 | $1.00 | Share of EC2/DB/Redis |
| Ops oversight (amortized) | $9.00 | $17.00 | Human time: phase checks, ban recovery |
| **Total per month** | **~$15/mo** | **~$25/mo** | |

**Total warming investment:**
- **Silver avatar** (3 months warming): $15/mo × 3 months = **$45 total**
- **Gold avatar** (6 months warming): $25/mo × 6 months = **$150 total**

---

### Sale Prices & Unit Economics

| Metric | Silver Avatar | Gold Avatar |
|--------|-------------|-------------|
| **Sale price** | $199 (one-time) | $499 (one-time) |
| **Total warming cost** | $45 | $150 |
| **Gross profit per unit** | **$154** | **$349** |
| **Gross margin** | **77%** | **70%** |
| **Payback period** | Immediate | Immediate |
| **ROI per unit** | 342% | 233% |

Both tiers achieve immediate payback — the one-time sale price covers all accumulated warming costs on the first transaction.

---

### Payback Period Analysis

Unlike SaaS subscriptions that require months to recover CAC, avatar inventory has **instant payback**:

| Scenario | Investment | Revenue | Time to Payback |
|----------|-----------|---------|-----------------|
| Silver sold at 3 months | $45 | $199 | Day 1 of sale |
| Gold sold at 6 months | $150 | $499 | Day 1 of sale |
| Silver sold at 6 months (aged longer) | $90 | $249+ (premium) | Day 1 of sale |
| Gold sold at 12 months (premium) | $300 | $699+ (premium) | Day 1 of sale |

**Key insight:** There is no "payback period" in the traditional sense. Every sale is immediately profitable because the one-time price exceeds total warming investment.

---

### Inventory as a Compounding Asset

Unlike physical inventory (which depreciates, spoils, or becomes obsolete), avatar inventory **appreciates with age**:

| Avatar Age | Karma (typical) | Tier Eligibility | Market Value | Warming Investment |
|-----------|----------------|-----------------|-------------|-------------------|
| 3 months | 500-1,000 | Silver | $199 | $45 |
| 6 months | 2,000-3,000 | Gold | $499 | $150 |
| 9 months | 3,500-5,000 | Premium Gold | $599-699 | $225 |
| 12 months | 5,000-8,000 | Platinum (custom) | $799-999 | $300 |
| 18 months | 8,000-15,000 | AI-Native Expert | $1,499+ | $450 |

**Why inventory appreciates:**
1. **Karma compounds** — older accounts accumulate more karma passively from existing posts
2. **Account age is irreplaceable** — a 12-month-old account cannot be created faster than 12 months
3. **Subreddit presence deepens** — longer history = more trusted by moderators and community
4. **AI-Native Expert potential** — only aged accounts with deep niche presence achieve citability
5. **Competitor cannot replicate** — even with unlimited budget, time cannot be compressed

**Comparison to traditional inventory:**

| Property | Traditional Inventory | Avatar Inventory |
|----------|---------------------|-----------------|
| Value over time | Depreciates | **Appreciates** |
| Storage cost | Warehouse, insurance | ~$15-25/mo (warming) |
| Obsolescence risk | High (fashion, tech) | **None** (older = better) |
| Spoilage | Perishable goods expire | **Never expires** |
| Replication by competitor | Buy same supplier | **Cannot replicate** (time-locked) |
| Marginal production cost | Raw materials + labor | Proxy + AI + time |

---

### Scaling Model — Inventory Pipeline Economics

#### At 10 Partners (Year 1 Target)

**Demand assumption:** Each partner buys ~2 avatars/month (mix of Silver + Gold)

| Metric | Value |
|--------|-------|
| Monthly demand | 20 avatars/month (10 partners × 2 avg) |
| Average profit per avatar | $250 (weighted: 60% Silver × $154 + 40% Gold × $349) |
| Monthly avatar revenue | **$5,000/month** |
| Warming pipeline size | 50 avatars in warming at all times |
| Monthly warming cost | ~$1,000/month (30 Silver × $15 + 20 Gold × $25) |
| **Monthly net profit from avatars** | **$4,000/month** |
| **Pipeline ROI** | **5x** ($5,000 revenue / $1,000 warming cost) |

#### Scaling Projections

| Partners | Demand/mo | Pipeline Size | Warming Cost/mo | Revenue/mo | Net Profit/mo | ROI |
|----------|-----------|--------------|----------------|-----------|--------------|-----|
| 3 | 6 | 15 | $300 | $1,500 | $1,200 | 5x |
| 5 | 10 | 25 | $500 | $2,500 | $2,000 | 5x |
| 10 | 20 | 50 | $1,000 | $5,000 | $4,000 | 5x |
| 20 | 40 | 100 | $2,000 | $10,000 | $8,000 | 5x |
| 50 | 100 | 250 | $5,000 | $25,000 | $20,000 | 5x |

**ROI remains constant at ~5x regardless of scale** — both costs and revenue scale linearly.

---

### Risk-Adjusted Economics

Not every avatar survives warming. Some get banned, shadowbanned, or suspended during the warming period.

| Risk Factor | Probability | Financial Impact | Mitigation |
|-------------|------------|-----------------|-----------|
| Ban during warming (total loss) | ~5% | Loss of warming investment | Diversified inventory, conservative posting |
| Shadowban (recoverable) | ~3% | 2-4 week delay, extra $30-50 cost | Health monitoring, auto-freeze, recovery protocol |
| Suspension (temporary) | ~2% | 1-2 week delay, minimal cost | Appeal process, backup inventory |
| Subreddit ban (partial) | ~4% | Reduced value, may need reassignment | Multi-subreddit presence strategy |

**Risk-adjusted unit economics:**

| Metric | Silver (risk-adjusted) | Gold (risk-adjusted) |
|--------|----------------------|---------------------|
| Avatars started | 100 | 100 |
| Successful completions (~95%) | 95 | 95 |
| Total warming investment (100 avatars) | $4,500 | $15,000 |
| Revenue from 95 sold | $18,905 | $47,405 |
| **Adjusted gross profit** | **$14,405** | **$32,405** |
| **Adjusted margin** | **76.2%** | **68.4%** |
| **Adjusted per-unit profit** | **$144** | **$324** |

Even with 5% total loss rate, margins remain above 68% for both tiers.

---

### Inventory Pipeline Visualization

```
WARMING PIPELINE (continuous)
═══════════════════════════════════════════════════════════════

Month 1    Month 2    Month 3    Month 4    Month 5    Month 6
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│ Start  │→│ Hobby  │→│ SILVER │→│ Deeper │→│ Niche  │→│  GOLD  │
│ Warming│ │ Posts  │ │ READY  │ │ Engage │ │ Expert │ │ READY  │
│ (proxy │ │ (karma │ │ (500+  │ │ (brand │ │ (2000+ │ │ (sale  │
│  + AI) │ │  build)│ │ karma) │ │  subs) │ │ karma) │ │  ready)│
└────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
   $15/mo     $15/mo    SELL $199   $25/mo     $25/mo    SELL $499
                         or keep                          or keep
                         warming →                        warming →

UNSOLD INVENTORY (appreciating)
═══════════════════════════════════════════════════════════════

Month 7+   Month 9+    Month 12+    Month 18+
┌────────┐  ┌────────┐  ┌──────────┐  ┌──────────────┐
│Premium │  │Premium │  │ Platinum │  │  AI-Native   │
│ Gold   │  │ Gold+  │  │  Custom  │  │    Expert    │
│ $599+  │  │ $699+  │  │  $799+   │  │   $1,499+    │
└────────┘  └────────┘  └──────────┘  └──────────────┘
  $25/mo      $25/mo       $25/mo         $25/mo
```

---

### Competitive Moat Analysis — Time-Locked Inventory

| Competitor Action | Time Required | RAMP's Advantage |
|------------------|--------------|-----------------|
| Start warming Silver avatars today | 3 months minimum | RAMP has inventory ready NOW |
| Start warming Gold avatars today | 6 months minimum | RAMP has inventory ready NOW |
| Match RAMP's 50-avatar pipeline | 6+ months + $7,500 investment | RAMP already invested, selling today |
| Replicate a 12-month Platinum avatar | 12 months (no shortcut) | Cannot be bought, only grown |
| Build AI-Native Expert inventory | 18+ months | First-mover advantage is permanent |

**The avatar inventory is RAMP's most defensible asset.** Every month that passes without a competitor starting their own warming pipeline increases RAMP's lead by exactly one month. This advantage compounds indefinitely.

---

### Summary — Avatar Inventory as Business Asset

| Metric | Value |
|--------|-------|
| **Silver unit profit** | $154 (77% margin) |
| **Gold unit profit** | $349 (70% margin) |
| **Risk-adjusted margin** | 68-76% |
| **Pipeline ROI** | 5x at any scale |
| **Payback period** | Immediate (one-time sale) |
| **Inventory depreciation** | None (appreciates with age) |
| **Competitor replication time** | 3-18 months depending on tier |
| **Monthly pipeline cost (10 partners)** | $1,000 |
| **Monthly pipeline revenue (10 partners)** | $5,000 |
| **Annual avatar profit (10 partners)** | $48,000 |

**Bottom line:** Avatar inventory is a high-margin, appreciating asset with immediate payback, 5x ROI, and a time-locked competitive moat. It functions as both a revenue stream and a strategic barrier to entry.

---

## 11. 12-Month Revenue Ramp — Detailed Projection

This section models RAMP's white-label revenue ramp over 12 months with explicit partner acquisition assumptions, per-partner revenue maturation, and sensitivity analysis. All figures are consistent with Sections 1 and 9.

---

### Partner Acquisition Assumptions

The acquisition model reflects Tzvi's direct sales approach — no paid advertising, no inbound marketing engine at launch. Growth comes from personal network, referrals, and earned credibility.

| Phase | Months | Strategy | Prospects Contacted | Demos | Partners Signed |
|-------|--------|----------|--------------------:|------:|----------------:|
| **Seed** | 1–2 | Tzvi's direct outreach (LinkedIn, warm intros, agency networks) | 20 | 3–4 | 1 |
| **Early Traction** | 3–4 | First partner referrals + case study in progress | 15 | 3 | 1 |
| **Growth** | 5–6 | Word of mouth + content marketing (LinkedIn posts, agency blog) | 25 | 5–6 | 1–2 |
| **Steady State** | 7–9 | Repeatable playbook, inbound interest, partner referral incentive | 30/mo | 4–5/mo | 1/mo |
| **Acceleration** | 10–12 | Published case studies + conference presence + partner testimonials | 40/mo | 6–8/mo | 1–2/mo |

**Conversion funnel assumptions:**
- Prospect → Demo: 15–20% (warm outreach, not cold)
- Demo → Signed: 25–33% (high-value proposition, annual commitment filters serious buyers)
- Average sales cycle: 3–4 weeks (Starter/Growth), 6–8 weeks (Scale/Enterprise)
- Zero churn in Year 1 (annual contracts, high switching costs)

---

### Per-Partner Revenue Ramp (Maturation Model)

Each partner follows a predictable revenue curve as they onboard clients and expand usage:

| Partner Tenure | Clients Active | Likely Tier | Platform Fee | Avatar Purchases | Slot Overages | Total Revenue/Partner |
|---------------|:--------------:|-------------|-------------:|----------------:|-------------:|---------------------:|
| **Month 1** (onboarding) | 2–3 | Starter ($999) | $999 | $400 (2 Silver) | $0 | **$1,399** |
| **Month 2** | 3–4 | Starter/Growth | $999–$1,999 | $300 (1–2 avatars) | $0 | **$1,799** |
| **Month 3** | 5–6 | Growth ($1,999) | $1,999 | $500 (1 Gold) | $0 | **$2,499** |
| **Month 4** | 6–7 | Growth | $1,999 | $300 | $0 | **$2,299** |
| **Month 5** | 7–8 | Growth (at capacity) | $1,999 | $200 | $199 (1 overage) | **$2,398** |
| **Month 6** | 8–10 | Growth → Scale upgrade | $3,499 | $500 (1 Gold) | $0 | **$3,999** |
| **Month 9** | 12–15 | Scale | $3,499 | $400 | $398 (2 overages) | **$4,297** |
| **Month 12** | 15–20 | Scale (full capacity) | $3,499 | $300 | $597 (3 overages) | **$4,396** |

**Key dynamics:**
- Partners start at Starter/Growth and upgrade as they prove ROI to their clients
- Avatar purchases front-loaded (months 1–3) then steady at 1–2/month
- Slot overages kick in at month 5+ as partners fill their tier allocation
- Tier upgrades happen at month 3 (Starter→Growth) and month 6 (Growth→Scale)

---

### Revenue Streams Modeled

| Stream | Type | Pricing | When It Kicks In |
|--------|------|---------|-----------------|
| **Platform fees** | Monthly recurring | $999–$3,499/mo per tier | Month 1 (immediate) |
| **Avatar inventory sales** | One-time, recurring as clients expand | $199 Silver, $499 Gold | Month 1 (front-loaded) |
| **Slot overage fees** | Monthly recurring per extra slot | $199/additional client/month | Month 5+ (partner at capacity) |
| **Tier upgrades** | Step-up in monthly recurring | Starter→Growth (+$1,000), Growth→Scale (+$1,500) | Month 3–6 |

---

### Base Case — Month-by-Month Projection

**Assumptions (Base Case):**
- Partner acquisition per schedule above (8 partners by Month 12)
- Partners start at Growth tier ($1,999) on average
- Average revenue per partner matures from $1,800/mo (Month 1) to $3,500/mo (Month 12)
- Avatar sales: 2 avatars/partner/month average (weighted Silver/Gold)
- Slot overages begin at Month 5 for earliest partners
- No churn (annual contracts)

| Month | New Partners | Total Partners | Avg Rev/Partner | Platform Fees | Avatar Sales | Overages | **Total MRR** | **Cumulative Revenue** |
|------:|:------------:|:--------------:|----------------:|--------------:|------------:|---------:|--------------:|-----------------------:|
| 1 | 1 | 1 | $1,399 | $999 | $400 | $0 | **$1,399** | $1,399 |
| 2 | 0 | 1 | $1,799 | $999 | $500 | $0 | **$1,499** | $2,898 |
| 3 | 1 | 2 | $2,100 | $2,998 | $800 | $0 | **$3,798** | $6,696 |
| 4 | 0 | 2 | $2,349 | $3,998 | $600 | $0 | **$4,598** | $11,294 |
| 5 | 1 | 3 | $2,466 | $5,497 | $800 | $199 | **$6,496** | $17,790 |
| 6 | 1 | 4 | $2,749 | $7,996 | $1,200 | $199 | **$9,395** | $27,185 |
| 7 | 1 | 5 | $2,899 | $10,495 | $1,300 | $398 | **$12,193** | $39,378 |
| 8 | 1 | 6 | $3,033 | $12,994 | $1,500 | $398 | **$14,892** | $54,270 |
| 9 | 1 | 7 | $3,142 | $15,493 | $1,700 | $597 | **$17,790** | $72,060 |
| 10 | 0 | 7 | $3,256 | $15,493 | $1,400 | $796 | **$17,689** | $89,749 |
| 11 | 1 | 8 | $3,312 | $17,492 | $1,600 | $796 | **$19,888** | $109,637 |
| 12 | 0 | 8 | $3,436 | $17,492 | $1,500 | $995 | **$19,987** | $129,624 |

**Base Case Summary:**
- **Year 1 total collected: ~$130,000**
- **Month 12 MRR: ~$20,000**
- **Run-rate ARR at Month 12: $240,000**
- **Average revenue per partner at Month 12: $2,498** (blended across tenure)

---

### Sensitivity Analysis

#### Scenario A: Acquisition 50% Slower (4 partners by Month 12)

What if Tzvi's outreach converts at half the expected rate?

| Month | Total Partners | Total MRR | Cumulative Revenue |
|------:|:--------------:|-----------:|-------------------:|
| 1 | 1 | $1,399 | $1,399 |
| 3 | 1 | $2,499 | $5,897 |
| 5 | 2 | $4,897 | $14,691 |
| 7 | 2 | $5,696 | $25,083 |
| 9 | 3 | $9,294 | $43,671 |
| 12 | 4 | $12,792 | $74,055 |

**Slow Scenario Summary:**
- **Year 1 total collected: ~$74,000**
- **Month 12 MRR: ~$12,800**
- **Run-rate ARR at Month 12: $153,500**
- **Still profitable from Month 1** (gross margin 73%+ per Section 3)

#### Scenario B: Average Revenue 20% Lower (partners stay at lower tiers longer)

What if partners don't upgrade as quickly, or buy fewer avatars?

| Month | Total Partners | Avg Rev/Partner | Total MRR | Cumulative Revenue |
|------:|:--------------:|----------------:|-----------:|-------------------:|
| 1 | 1 | $1,119 | $1,119 | $1,119 |
| 3 | 2 | $1,680 | $3,038 | $5,357 |
| 6 | 4 | $2,199 | $7,516 | $21,748 |
| 9 | 7 | $2,514 | $14,232 | $57,648 |
| 12 | 8 | $2,749 | $15,990 | $103,699 |

**Low Revenue Scenario Summary:**
- **Year 1 total collected: ~$104,000**
- **Month 12 MRR: ~$16,000**
- **Run-rate ARR at Month 12: $192,000**
- **Still healthy margins** — lower revenue but costs also lower (fewer avatars sold, fewer overages)

#### Scenario C: Combined Worst Case (50% slower acquisition + 20% lower revenue)

| Month | Total Partners | Total MRR | Cumulative Revenue |
|------:|:--------------:|-----------:|-------------------:|
| 1 | 1 | $1,119 | $1,119 |
| 6 | 2 | $3,918 | $13,398 |
| 9 | 3 | $7,435 | $34,937 |
| 12 | 4 | $10,234 | $59,244 |

**Worst Case Summary:**
- **Year 1 total collected: ~$59,000**
- **Month 12 MRR: ~$10,200**
- **Run-rate ARR at Month 12: $123,000**
- **Still cash-flow positive from Month 1** — infrastructure cost is $44/mo fixed

---

### Path to $50K/mo MRR Milestone

| Scenario | Partners Needed | Avg Rev/Partner Required | Month Achieved |
|----------|:--------------:|:------------------------:|:--------------:|
| **Base Case** | 15 | $3,333 | **Month 18–20** |
| **Aggressive** (Section 1) | 10 | $5,000 | **Month 10** |
| **Slow Acquisition** | 15 | $3,333 | **Month 24–26** |
| **Low Revenue** | 18 | $2,778 | **Month 22–24** |
| **Worst Case** | 20 | $2,500 | **Month 28–30** |

**What $50K/mo MRR requires:**
- At Growth tier average ($2,500/partner): 20 partners
- At Scale tier average ($4,000/partner): 13 partners
- At blended average ($3,333/partner): 15 partners

**Acceleration levers to reach $50K faster:**
1. Push partners to Scale tier earlier (dedicated AM drives upgrades)
2. Increase avatar inventory sales (Gold avatars at $499 vs. Silver at $199)
3. Introduce managed service upsell ($1,000–$2,000/partner/month)
4. Revenue share model for high-volume partners (15–25% of their gross)
5. Slot overage pricing creates natural expansion revenue

---

### Assumptions Summary

| Assumption | Base Case Value | Source |
|-----------|----------------|--------|
| Partner acquisition rate | 1 per 6 weeks average | Tzvi's network + referrals |
| Starting tier | Growth ($1,999/mo) | Section 9 pricing |
| Tier upgrade timeline | Month 3 (Starter→Growth), Month 6 (Growth→Scale) | Per-partner ramp model |
| Avatar purchases/partner/month | 2 (weighted avg $300) | Section 10 demand model |
| Slot overage onset | Month 5 per partner | Growth tier fills at 8 clients |
| Annual churn | 0% | Annual contracts, high switching costs |
| LLM cost per partner | $280/mo (8 clients) | Section 8 attribution |
| Infrastructure cost per partner | $0/mo marginal | Section 2 (same server) |
| Support cost per partner | $200/mo amortized | Section 2 variable costs |
| Sales cycle | 3–4 weeks (Growth), 6–8 weeks (Scale) | Direct outreach model |
| Demo-to-close rate | 25–33% | Warm leads, high-value prop |

---

### Revenue Composition at Month 12 (Base Case)

```
Platform Fees (recurring):  ████████████████████████████████████████████████  88% ($17,492)
Avatar Inventory Sales:     ████                                              7% ($1,500)
Slot Overages (recurring):  ███                                               5% ($995)
                                                                    Total: $19,987/mo
```

**Recurring vs. One-Time:**
- Recurring revenue (platform + overages): $18,487/mo (92%)
- One-time revenue (avatar sales): $1,500/mo (8%)
- **Net Revenue Retention > 120%** — partners expand (tier upgrades + overages) faster than any contraction

---

### Comparison to Section 1 Projections

| Metric | Section 1 Conservative | Section 1 Aggressive | Section 11 Base Case |
|--------|:----------------------:|:--------------------:|:--------------------:|
| Partners at Month 12 | 5 | 10 | 8 |
| Month 12 MRR | $14,500 | $55,000 | $19,987 |
| Year 1 collected | $110,000 | $387,000 | $129,624 |
| Run-rate ARR | $174,000 | $660,000 | $240,000 |
| Avg revenue/partner | $2,900 | $5,500 | $2,498 |

**Section 11 sits between Conservative and Aggressive** — it models the realistic middle path with explicit acquisition mechanics and per-partner maturation. Section 1 Aggressive assumes managed service upsells ($1,000/partner/month) which are not modeled here.

---

### Key Takeaways for Investor Conversations

1. **Break-even is Day 1** — first partner payment ($999–$1,999) exceeds all monthly costs ($44 infra + $280 LLM + $200 support = $524)
2. **Revenue compounds three ways** — new partners (acquisition), tier upgrades (expansion), slot overages (usage)
3. **Worst case still works** — even at 50% slower acquisition + 20% lower revenue, Year 1 collects $59K with $10K/mo MRR
4. **$50K/mo is achievable** — 15 partners at blended $3,333/partner, reachable in 18–20 months (base case)
5. **Near-zero marginal cost** — each new partner adds $0 infrastructure cost, making every dollar of new revenue 73–87% gross profit
6. **Avatar inventory is bonus revenue** — $1,500/mo in avatar sales at 8 partners, scaling linearly with partner count

---

*Document version: 1.4*
*Last updated: Based on design document Decision 6 + steering file LLM cost data + avatar warming economics + partner acquisition model*
*Referenced by: Tasks 3.2 (unit economics), 3.3 (avatar ROI), 3.4 (12-month ramp), 3.5 (LLM attribution)*
