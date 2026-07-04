# Reddit Posting Automation — System Design (Ori, Mar 2026)

> Saved from Ori handoff materials. Describes n8n + GoLogin + Puppeteer automation.
> Key value: Human behavior simulation specs (typing, scrolling, mouse movement).
> These specs are directly applicable if RAMP extension needs typing simulation.

## Key Extractions for RAMP

### Human Behavior Simulation Specs

#### Mouse Movement (ghost-cursor library)
- Bézier curve paths between points
- Variable speed: fast across open space, slow near targets
- Micro-tremors, slight overshoot and self-correction
- Between actions: drift cursor to random mid-screen position

#### Typing Simulation
- Inter-keystroke delay: 70-190ms (variable, not uniform)
- 5% chance of 500-2000ms "thinking pause" mid-comment
- Typo rate: ~1.5% per alphabetic character
- Two typo modes:
  - Immediate fix (50%): wrong key → pause 300-600ms → Backspace → retype
  - Delayed fix (50%): wrong key → continue 3-15 chars → arrow-back → fix → arrow-forward

#### QWERTY Adjacency Map (for realistic typos)
```javascript
const ADJACENT_KEYS = {
  q:['w','a'],       w:['q','e','a','s'],
  e:['w','r','s','d'], r:['e','t','d','f'],
  t:['r','y','f','g'], y:['t','u','g','h'],
  u:['y','i','h','j'], i:['u','o','j','k'],
  o:['i','p','k','l'], p:['o','l'],
  a:['q','w','s','z'], s:['a','d','w','e','z','x'],
  d:['s','f','e','r','x','c'], f:['d','g','r','t','c','v'],
  g:['f','h','t','y','v','b'], h:['g','j','y','u','b','n'],
  j:['h','k','u','i','n','m'], k:['j','l','i','o','m'],
  l:['k','o','p'], z:['a','x'], x:['z','c','s','d'],
  c:['x','v','d','f'], v:['c','b','f','g'],
  b:['v','n','g','h'], n:['b','m','h','j'],
  m:['n','j','k'],
};
```

#### Scrolling
- Variable amounts (200-600px per scroll)
- 25% chance of scroll-back (re-reading)
- Pause 600-2500ms between scrolls ("reading" what scrolled into view)

### Session Structure (validates RAMP extension approach)
- Warm-up (3-5 min): homepage scroll, upvote 3-5 posts
- Hobby visit (2-4 min): scroll, upvote, maybe hobby comment
- Strategic comment (5-10 min): navigate via subreddit/new → find by title → comment
- Filler break (3-7 min): homepage or hobby browsing
- Minimum 4 minutes between any two comments
- Never two strategic comments back-to-back

### Post-Finding Logic
- Navigate to r/subreddit/new/ (not direct URL)
- Scroll-and-match by title (first 50 chars, case-insensitive)
- Up to 20 scroll passes before fallback to search
- Fallback: subreddit search with first 6 words of title

### Timing Between Comments
- Minimum 4 minutes between comments (RAMP uses 3 min — close match)
- Maximum 12 minutes (randomized)

## Comparison to Current RAMP Extension

| Aspect | Ori's Design (Puppeteer) | RAMP Extension v3 (Chrome MV3) |
|--------|--------------------------|-------------------------------|
| Text insertion | Character-by-character with typos | Bulk `textarea.value = text` |
| Mouse movement | ghost-cursor Bézier curves | Standard .click() / scrollIntoView |
| Scrolling | 200-600px variable + scroll-back | 300-600px random + smooth behavior |
| Navigation | Subreddit → find by title → click | Subreddit → find by thread_id → click |
| Timing | 70-190ms per keystroke | Instant (bulk insert) |
| Typo simulation | 1.5% rate + adjacent key map | None |
| Inter-step delays | 3-7 min fillers, varied pauses | 1.5-3s random pauses |

## When to Add Typing Simulation to RAMP Extension

The A/B test framework (`extension-posting-ab-test` spec) will determine if Reddit detects
programmatic posting via old.reddit textarea. If the `old_reddit` group shows elevated
shadowban rates vs `manual_email`:
1. Implement character-by-character typing (Ori's 70-190ms inter-keystroke)
2. Add occasional typos with adjacent-key correction
3. Add longer inter-step delays (4-12 min between comments)

Until A/B test results show a problem, bulk insertion is simpler and more reliable.

## Full Document

[See original PDF/attachment in Tzvi's email for complete text]
