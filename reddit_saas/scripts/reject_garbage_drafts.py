"""One-off script: reject pending drafts that fail the quality gate.

Finds all pending CommentDrafts, runs them through draft_quality_gate,
and auto-rejects any that fail. Safe to run multiple times (idempotent).

Usage:
  # Local:
  cd reddit_saas && python scripts/reject_garbage_drafts.py

  # Production (inside Docker):
  docker compose exec app python scripts/reject_garbage_drafts.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.comment_draft import CommentDraft
from app.services.draft_quality_gate import validate_draft_text


def main():
    db = SessionLocal()
    try:
        pending = (
            db.query(CommentDraft)
            .filter(CommentDraft.status == "pending")
            .all()
        )

        print(f"Found {len(pending)} pending drafts. Checking quality...")

        rejected = 0
        for draft in pending:
            text = draft.ai_draft or ""
            qr = validate_draft_text(text)
            if not qr.ok:
                draft.status = "rejected"
                rejected += 1
                print(f"  ❌ REJECTED draft {draft.id}: reason={qr.reason} text={repr(text[:60])}")

        if rejected:
            db.commit()
            print(f"\n✅ Rejected {rejected} garbage drafts out of {len(pending)} pending.")
        else:
            print(f"\n✅ All {len(pending)} pending drafts pass quality gate. Nothing to reject.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
