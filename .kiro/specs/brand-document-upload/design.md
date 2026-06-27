# Brand Document Upload — Design

## Architecture

```
Client uploads PDF/DOCX/TXT
         │
         ▼
┌─────────────────────────┐
│ FastAPI endpoint         │
│ /clients/{id}/documents  │  ← validates format, size, count
│ saves to filesystem/S3   │
└─────────┬───────────────┘
          │ (async)
          ▼
┌─────────────────────────┐
│ Celery Task:            │
│ extract_document_voice   │  ← Gemini Flash, single call
│ (parse → extract → save) │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ ClientDocument record    │
│ status: extracted        │
│ extract: {rules, style}  │
└─────────┬───────────────┘
          │ (client reviews)
          ▼
┌─────────────────────────┐
│ Client confirms extract  │  ← HTMX partial
│ Status → "active"        │
└─────────┬───────────────┘
          │
          ▼
┌─────────────────────────┐
│ Injected into generation │
│ prompt as voice context  │  ← next pipeline run
└─────────────────────────┘
```

## New Model: ClientDocument

```python
class ClientDocument(Base):
    __tablename__ = "client_documents"

    id: UUID (pk)
    client_id: UUID (FK → clients)
    filename: str  # original filename
    file_path: str  # storage path (local or S3 key)
    file_size_bytes: int
    mime_type: str  # application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, text/plain
    
    # Extraction
    status: str  # "uploaded" | "extracting" | "extracted" | "active" | "rejected" | "failed"
    raw_text_preview: str | None  # first 500 chars (for admin debug)
    extract: dict | None  # JSONB: {voice_rules: [], topic_prefs: [], forbidden: [], style_summary: str}
    extract_token_count: int | None  # how many tokens the extract uses
    extraction_error: str | None
    
    # Lifecycle
    uploaded_at: datetime
    extracted_at: datetime | None
    activated_at: datetime | None  # when client confirmed
    uploaded_by_user_id: UUID (FK → users)
    
    # Soft delete
    is_deleted: bool = False
    deleted_at: datetime | None
```

## Extraction Prompt

```
You are extracting brand voice principles from a company document for use in Reddit comment generation.

DOCUMENT TEXT:
{document_text_first_8000_chars}

EXISTING BRAND VOICE (for context — do NOT repeat this, only ADD new insights):
{client.brand_voice}

EXTRACT the following (JSON):
{
  "voice_rules": ["max 5 rules: HOW the brand communicates — tone, formality, sentence style"],
  "topic_preferences": ["max 3: what topics/themes the brand gravitates toward"],
  "forbidden_patterns": ["max 3: what to NEVER say — from the document's own guidelines"],
  "style_summary": "1 sentence: the communication personality in Reddit terms"
}

CRITICAL RULES:
- Extract STYLE, not CONTENT. No product claims, no customer names, no revenue data.
- Strip ALL marketing language: no "revolutionary", "game-changing", "best-in-class", "leading"
- Output must be Reddit-appropriate — not corporate press-release language
- If document is mostly marketing fluff with no real voice guidance, return fewer rules
- Each rule should be actionable (tells a writer WHAT TO DO, not what the brand IS)
```

## File Parsing

| Format | Library | Approach |
|--------|---------|----------|
| PDF | `pymupdf` (fitz) | Extract text pages, concatenate. Skip image-only pages. |
| DOCX | `python-docx` | Paragraphs → text. Ignore tables/images. |
| TXT | built-in | Read as UTF-8 |

Token limit for extraction: send first 8000 chars of extracted text to LLM (covers ~20 pages of dense text).

## Injection into Generation Prompt

When `generate_comment` builds the prompt:

```python
# In services/generation.py, after voice_profile assembly:
doc_context = get_active_document_extract(client_id, db)
if doc_context:
    voice_section += f"\n\nAdditional voice context (from brand documents):\n{doc_context}"
```

`get_active_document_extract(client_id)`:
- Queries ClientDocument WHERE client_id AND status="active" AND NOT is_deleted
- Concatenates all active extracts (voice_rules + style_summary)
- Truncates to 500 tokens max
- Returns formatted string or empty string

## UI: Client Portal

### Settings > Brand Documents

```
┌─────────────────────────────────────┐
│ 📄 Brand Documents                   │
│                                      │
│ ┌─────────────────────────────────┐ │
│ │ brand-guidelines-v2.pdf (2.3MB) │ │
│ │ Status: ✓ Active                │ │
│ │ Extracted: 4 voice rules        │ │
│ │ [View Extract] [Remove]         │ │
│ └─────────────────────────────────┘ │
│                                      │
│ ┌─────────────────────────────────┐ │
│ │ sales-deck-q2.pdf (5.1MB)       │ │
│ │ Status: ⏳ Review needed         │ │
│ │ [Review Extract] [Reject]       │ │
│ └─────────────────────────────────┘ │
│                                      │
│ [+ Upload Document] (3/5 used)      │
└─────────────────────────────────────┘
```

### Review Extract Modal/Partial

```
┌─────────────────────────────────────┐
│ Extracted from: brand-guidelines.pdf │
│                                      │
│ Voice Rules:                         │
│ • Be direct and technical — avoid    │
│   hedging language                   │
│ • Use first-person experience        │
│   ("In my work with..." not "It is") │
│ • Prefer specific numbers over       │
│   vague claims                       │
│                                      │
│ Style: "Confident practitioner who   │
│ backs opinions with experience"      │
│                                      │
│ [✓ Accept & Activate] [✏️ Edit] [✗] │
└─────────────────────────────────────┘
```

## Lifecycle: New Document Added After Pipeline Running

```
Day 1: Pipeline running with brand_voice + tone anchors
Day 5: Client uploads new-brand-book.pdf
  → Extract runs (30s)
  → Client reviews: "3 new rules found"
  → Client clicks "Accept"
  → extract.status = "active", activated_at = now()
  
Day 5 pipeline run (already in progress): NO CHANGE (uses old context)
Day 6 pipeline run (08:00): picks up new extract automatically
  → generation prompt now includes new rules
  
Activity Event: "Brand document 'new-brand-book.pdf' activated. 
  New voice rules will apply starting next pipeline cycle."
```

## Priority & Override Rules

1. **tone_calibration_anchors** (sentences rated 4-5) — HIGHEST priority
2. **brand_voice** (manual text) — HIGH
3. **document_extracts** (AI-extracted) — SUPPLEMENTARY
4. **AI-suggested voice** (from step4_suggest) — LOWEST (fallback only)

If document extract conflicts with tone anchors or brand_voice, the manual/calibrated rules win. Extraction prompt already knows about existing brand_voice and avoids repeating.

## Migration

```sql
-- alembic migration: bdu01
CREATE TABLE client_documents (
    id UUID PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES clients(id),
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    raw_text_preview TEXT,
    extract JSONB,
    extract_token_count INTEGER,
    extraction_error TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    extracted_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ,
    uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_client_documents_client_active 
  ON client_documents(client_id) WHERE status = 'active' AND NOT is_deleted;
```

## Dependencies

- `pymupdf` (PDF parsing) — add to pyproject.toml
- `python-docx` (DOCX parsing) — add to pyproject.toml
- File storage: local `uploads/` dir (dev) or DO Spaces (prod)
- Existing: Gemini Flash, Celery, client portal templates
