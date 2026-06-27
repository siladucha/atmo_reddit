# Brand Document Upload — Requirements

## Context

Clients want to upload brand documents (tone of voice guides, sales decks, brand books, case studies) to improve AI-generated content quality. The system should extract voice/tone principles from these documents — NOT inject raw text into prompts.

**Core principle:** Documents are supplementary. Manual input (brand_voice, tone calibration anchors) is primary. Documents cannot override what the client typed manually.

## Problem Statement

- AI generates comments based on brand_voice text field (2-3 sentences) — too thin
- Clients have rich brand guidelines in PDF/DOCX that AI cannot access
- Manual voice calibration captures style but misses terminology, domain concepts, forbidden phrases
- Without document context, AI produces generically "correct" but not brand-specific output

## Requirements

### FR-1: Document Upload

- Client can upload documents from: Onboarding Step 4 (voice section) OR Settings > Profile > Brand Documents
- Supported formats: PDF, DOCX, TXT
- Limits: max 5 documents per client, max 10MB each
- Upload is async (Celery task parses in background, UI shows progress)
- Documents stored in DO Spaces (S3-compatible) or local filesystem (dev)

### FR-2: AI Extraction (NOT raw injection)

On upload, system runs ONE LLM call per document to extract:
- 3-5 **voice rules** (how the brand speaks — tone, formality, vocabulary preferences)
- 2-3 **topic preferences** (what topics the brand gravitates toward)
- 1-2 **forbidden patterns** (what to never say — from the document's own guidelines)
- **communication_style** (1 sentence summary)

Output: structured extract (~200-300 tokens). This is what gets injected into generation prompts — NOT the raw 50-page PDF.

### FR-3: Client Review Before Activation

- After extraction, client sees: "Here's what we learned from [filename]:"
- Client can: Accept, Edit, or Reject the extracted rules
- Only ACCEPTED extracts are applied to pipeline
- If client rejects — document is stored but not used

### FR-4: Incremental Updates (new documents added later)

When client uploads a new document AFTER pipeline is running:
1. New extract is APPENDED to existing brand context (not replace)
2. Current pending/approved drafts are NOT affected (old context)
3. New context applies starting from next pipeline generation cycle
4. Activity event: "Brand context updated — changes apply from next cycle"

Client can also:
- **Replace all** document rules (explicit action with confirmation)
- **Delete** a document → its extracted rules are removed from brand_voice
- **Re-extract** a document (if extraction was poor quality)

### FR-5: Safety Extraction Filter

The extraction LLM call MUST:
- Strip all marketing language (buzzwords, superlatives, "revolutionary")
- Strip confidential data (customer names, revenue numbers, pricing)
- Strip competitor bashing language
- Output only STYLE rules, not CONTENT claims
- Add implicit safety wrapper: "within Reddit community norms"

### FR-6: Runtime Injection

- Extracted rules stored as tagged section in brand_voice: `\n\nFrom [filename] (added DATE):\n- rule 1\n- rule 2`
- OR stored in separate JSONB field `document_extracts` on Client model (cleaner)
- Injected into comment_generation prompt as additional voice context
- Token budget: max 500 tokens total from all document extracts per generation call
- If multiple documents exceed budget: most recent documents prioritized

### FR-7: Visibility

- Admin panel: sees all uploaded documents + extracts per client
- Partner dashboard: sees document count per client
- Client portal (Settings): full document management UI (upload, view extract, delete)

## Non-Functional Requirements

### NFR-1: Cost

| Operation | Cost |
|-----------|------|
| Storage (50MB/client × 100 clients) | $0.10/mo |
| Extraction LLM (1 call per upload) | $0.001 per document |
| Runtime injection (0 extra — extract is tiny) | $0 (within existing token budget) |
| **Total monthly (10 clients, 5 docs each)** | **< $0.15/mo** |

### NFR-2: Performance

- Upload: instant (file saved, extraction queued)
- Extraction: < 30s (Gemini Flash, single call)
- No impact on pipeline latency (extract pre-computed, stored in DB)

### NFR-3: Security

- Files stored outside web root (not publicly accessible)
- No raw document content stored in prompts or logs
- Extraction strips PII/confidential data by design
- File content never sent to external services beyond LLM extraction call

## Risks & Mitigations

### Onboarding Phase

| Risk | Mitigation |
|------|-----------|
| Client uploads marketing deck → extracted tone is corporate | Extraction prompt explicitly filters marketing language |
| Parsing fails (scanned PDF, encrypted) | Graceful error: "Could not read this file. Try TXT or a different format." |
| Client uploads 5 irrelevant files | Each extract is reviewable — client sees what was extracted |

### Ongoing (post-activation)

| Risk | Mitigation |
|------|-----------|
| New doc contradicts existing voice | Append model — new rules ADD, don't override. Manual brand_voice always primary. |
| Client updates tone drastically mid-campaign | Only new drafts affected. Old in-flight drafts keep old context. |
| Document extract drifts from actual Reddit voice | Tone calibration anchors (rated 4-5) take priority over document rules |

### Karma Down

| Risk | Mitigation |
|------|-----------|
| Extracted "professional" tone clashes with casual subreddit | Subreddit emotional profile + compatibility scoring still apply (separate system) |
| Too much context → AI loses focus → verbose comments | Hard token cap: 500 tokens from docs. Beyond that = truncated. |
| Brand language leaks through despite filter | Post-generation editor (EDITOR_PROMPT) provides second safety layer |

### Ban Risk

| Risk | Mitigation |
|------|-----------|
| Confidential info in doc → appears in Reddit comment | Extraction strips: names, numbers, case studies. Only STYLE survives. |
| Aggressive competitor language in doc → avatar uses it | Extraction filter: "NO competitor mentions, NO negative claims about others" |
| Self-promotional language in brand doc → avatar sounds like ad | Existing COMMENT_WRITER_PROMPT hard rule: "NEVER mention brand" still enforced |

## Success Criteria

1. Client uploads PDF → within 30s sees "3 rules extracted"
2. Extracted rules are visibly different from raw marketing speak
3. Comments generated with document context score higher in tone calibration (>= 4 average)
4. Zero incidents of confidential data leaking into Reddit comments
5. No karma degradation attributable to document upload (compared to baseline)

## Out of Scope

- OCR for scanned PDFs (text-based only)
- Image/chart extraction from documents
- Multi-language document support (English only for MVP)
- Automatic document refresh (client must re-upload if source changes)
- RAG/embedding-based retrieval (overkill — extract is sufficient)
