# Reddit Proxy & Browser Setup — Complete Reference (Ori, Feb 2026)

> Saved from Ori handoff materials. See original attachments in Tzvi's email (July 4, 2026).
> Key value: Bright Data credentials, GoLogin workflow, account warming protocol.

## Key Extractions for RAMP

### Bright Data Credentials
- Host: `brd.superproxy.io`
- Port: `33335`
- Customer ID: `hl_427f1437`
- Zone: `isp_proxy_cointelligent_reddit`
- Username format: `brd-customer-hl_427f1437-zone-isp_proxy_cointelligent_reddit-ip-[DEDICATED_IP]`
- First allocated IP: `158.46.218.55`
- Test URL: `https://geo.brdtest.com/mygeo.json`

### Account Warming (matches RAMP Phase 0)
- Days 1-3: Passive (scroll, upvote 2-3 posts, no comments)
- Days 4-7: Karma building (r/AskReddit, r/aww, r/gaming — "Rising" sort)
- Day 8+: Hobby engagement → industry engagement after karma floor (50-100)

### Infrastructure Choices
- ISP Dedicated proxies (not datacenter, not rotating)
- GoLogin (Orbita browser) for fingerprint isolation
- One IP per avatar permanently — never shared
- VPN only for initial login (reCAPTCHA workaround)

### Known Limitation
- Bright Data ISP blocks google.com (breaks reCAPTCHA)
- Workaround: first login via VPN, then switch to proxy

## Full Document

[See original PDF/attachment in Tzvi's email for complete text]
