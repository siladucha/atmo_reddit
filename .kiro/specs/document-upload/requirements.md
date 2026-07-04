# Document Upload for Voice & Brand Context

## Problem Statement

Clients have existing brand documents (tone of voice guides, sales decks, product briefs) that define how their brand communicates. Currently this context is captured only through the onboarding wizard's free-text fields. Tzvi's feedback (June 26): "I think it would be best to let the client the ability to add documents (tone of voice, sales decks, etc.)"

## Requirements

### FR-1: Document Upload

1. THE client portal (Settings or dedicated "Brand" page) SHALL allow uploading documents:
   - Accepted formats: PDF, DOCX, TXT, MD
   - Max size: 10 MB per file
   - Max files per client: 10
2. EACH uploaded document SHALL have:
   - `filename`: original name
   - `doc_type`: "tone_of_voice" | "sales_deck" | "product_brief" | "competitor_analysis" | "other"
   - `description`: optional text (what is this document about)
   - `uploaded_by`: user who uploaded
   - `uploaded_at`: timestamp
   - `text_content`: extracted text (for LLM consumption)
   - `is_active`: boolean (can be disabled without deleting)

### FR-2: Text Extraction

1. UPON upload, THE system SHALL extract plain text from the document:
   - PDF: via `pymupdf` (fitz) or `pdfplumber`
   - DOCX: via `python-docx`
   - TXT/MD: direct read
2. THE extracted text SHALL be stored in `text_content` field (max 50,000 chars, truncated with notice)
3. IF extraction fails → store error, mark document as `extraction_failed`, notify uploader

### FR-3: Document Influences Generation

1. WHEN generating comments for a client, THE system SHALL include relevant document context:
   - `tone_of_voice` documents → injected into voice/style section of generation prompt
   - `product_brief` documents → injected into knowledge/context section
   - `sales_deck` → used for benefit framing (what problems we solve)
2. THE injection SHALL be truncated to fit token budget:
   - Max 2000 chars from tone_of_voice docs (most important)
   - Max 1000 chars from product/sales docs
   - Selected by recency (newest active document wins if multiple of same type)
3. THE prompt injection SHALL be clearly separated: `[CLIENT BRAND CONTEXT]...[END BRAND CONTEXT]`

### FR-4: Admin & Portal UI

1. **Client Portal** (Settings page): Upload button, list of documents, toggle active/inactive, delete
2. **Admin Panel** (Client detail): View uploaded documents, download originals, toggle active
3. **Onboarding wizard** (optional): "Upload brand documents" link on Step 4 (Voice & Keywords) — non-blocking

## Data Model

1. New model `ClientDocument`:
   - `id`: UUID PK
   - `client_id`: FK to clients
   - `filename`: String(255)
   - `doc_type`: String(30)
   - `description`: Text, nullable
   - `file_path`: String(500) — path on disk or object storage
   - `text_content`: Text — extracted text for LLM
   - `char_count`: Integer
   - `is_active`: Boolean, default True
   - `extraction_status`: String(20) — "success" | "failed" | "pending"
   - `uploaded_by`: FK to users, nullable
   - `uploaded_at`: DateTime
2. File storage: local filesystem (`/app/uploads/clients/{client_id}/`) for MVP
   - Future: migrate to DigitalOcean Spaces (S3-compatible) when needed

## Non-Functional Requirements

### NFR-1: Security
- Files stored outside web root (not directly accessible via URL)
- Download only through authenticated endpoint with client_id scope check
- Virus/malware scanning: out of scope for MVP (trusted clients only)

### NFR-2: Performance
- Text extraction runs synchronously on upload (PDF < 10MB = < 5s typically)
- LLM prompt assembly reads from DB (text_content field), not from file each time
- No upload during generation — documents are pre-processed

### NFR-3: Storage
- 10 files × 10 MB × 10 clients = 1 GB max (fits on current 60GB droplet)
- Extracted text: 50K chars × 10 docs × 10 clients = 5MB in DB (negligible)

## Out of Scope

- Real-time document processing (parsing while generating)
- Document versioning (replace = delete old + upload new)
- OCR for scanned PDFs (text-only extraction)
- DigitalOcean Spaces / S3 (future, not needed at current scale)
- Sharing documents between clients

## Dependencies

- File upload endpoint (new, FastAPI UploadFile)
- Text extraction libraries: `pymupdf` or `pdfplumber` (PDF), `python-docx` (DOCX)
- Generation service prompt assembly (exists, needs document injection)
- Alembic migration for `client_documents` table

## Success Criteria

1. Client uploads a "Tone of Voice" PDF → extracted text appears in document list
2. Next generated comment reflects language/style from the uploaded document
3. Client can disable a document → generation stops using it immediately
4. 10 MB PDF uploads and extracts in < 10 seconds
