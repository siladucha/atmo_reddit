# Brand Document Upload — Implementation Tasks

## Task 1: Model + Migration
- [ ] Create `ClientDocument` model (`app/models/client_document.py`)
- [ ] Alembic migration `bdu01` (table + index)
- [ ] Add relationship to Client model

## Task 2: File Parsing Service
- [ ] Create `app/services/document_parser.py`
- [ ] `parse_pdf(file_path) → str` (pymupdf)
- [ ] `parse_docx(file_path) → str` (python-docx)
- [ ] `parse_txt(file_path) → str`
- [ ] `parse_document(file_path, mime_type) → str` (dispatcher)
- [ ] Truncate to first 8000 chars
- [ ] Add `pymupdf`, `python-docx` to pyproject.toml

## Task 3: Extraction Service
- [ ] Create `app/services/document_extraction.py`
- [ ] `extract_voice_from_document(text, existing_brand_voice) → dict`
- [ ] Gemini Flash call with safety extraction prompt
- [ ] Returns: `{voice_rules: [], topic_preferences: [], forbidden_patterns: [], style_summary: str}`
- [ ] Token counting for extract (tiktoken or len-based approximation)

## Task 4: Celery Task
- [ ] Create `app/tasks/document_extraction.py`
- [ ] `extract_document_voice_task(document_id)` — parse + extract + save
- [ ] Error handling: sets status="failed" + extraction_error
- [ ] DistributedLock to prevent double-extraction

## Task 5: Upload Endpoint
- [ ] `POST /clients/{id}/documents/upload` — multipart file upload
- [ ] Validate: format (PDF/DOCX/TXT), size (<=10MB), count (<=5 per client)
- [ ] Save file to `uploads/{client_id}/{uuid}_{filename}`
- [ ] Create ClientDocument record (status="uploaded")
- [ ] Dispatch extraction task
- [ ] Return HTMX partial with "Extracting..." status

## Task 6: Review & Activate Endpoints
- [ ] `GET /clients/{id}/documents` — list documents with status
- [ ] `GET /clients/{id}/documents/{doc_id}/extract` — view extract partial
- [ ] `POST /clients/{id}/documents/{doc_id}/activate` — confirm extract
- [ ] `POST /clients/{id}/documents/{doc_id}/reject` — reject (keep file, don't use)
- [ ] `POST /clients/{id}/documents/{doc_id}/delete` — soft-delete (remove from pipeline)
- [ ] `POST /clients/{id}/documents/{doc_id}/re-extract` — re-run extraction

## Task 7: Client Portal UI
- [ ] Add "Brand Documents" section to Settings page (below Voice Feedback)
- [ ] Upload form (file input + submit)
- [ ] Document list with status badges
- [ ] Review partial (show extracted rules, Accept/Edit/Reject buttons)
- [ ] HTMX: upload → polling for extraction → show result

## Task 8: Pipeline Integration
- [ ] `get_active_document_extract(client_id, db) → str`
- [ ] Inject into `services/generation.py` comment generation prompt
- [ ] Token budget enforcement (max 500 tokens from docs)
- [ ] Test: generation with and without document context

## Task 9: Onboarding Integration
- [ ] Add optional upload section to Step 4 (Voice & Keywords)
- [ ] "Upload brand guide (optional)" — same upload flow
- [ ] Non-blocking: onboarding continues even if extraction is pending

## Task 10: Admin Visibility
- [ ] Admin client detail: show uploaded documents + extracts
- [ ] Admin can view/delete documents for any client
- [ ] Activity event on upload/activate/delete

## Task 11: Testing & Deploy
- [ ] Test upload flow (PDF, DOCX, TXT)
- [ ] Test extraction quality (marketing doc → clean rules)
- [ ] Test safety: confidential data NOT in extract
- [ ] Test pipeline: comments use document context
- [ ] Test update scenario: new doc added mid-campaign
- [ ] Deploy to staging → verify → production
