@router.post("/clients/{client_id}/drafts/{draft_id}/mark-posted")
def portal_mark_posted(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    reddit_url: str = Form(""),
):
    """Mark an approved draft as posted on Reddit."""
    try:
        if user.user_role == UserRole.client_viewer:
            return JSONResponse(status_code=403, content={"message": "Viewers cannot mark drafts as posted"})

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
        if not avatar or str(client_id) not in (avatar.client_ids or []):
            logger.warning(
                "Portal mark-posted: client_id mismatch | draft_id=%s | client_id=%s | avatar_client_ids=%s",
                draft_id, client_id, avatar.client_ids if avatar else None,
            )
            return JSONResponse(status_code=404, content={"message": "Draft not found"})

        if draft.status not in ("approved", "pending"):
            return JSONResponse(status_code=422, content={"message": "Draft is not in approved state"})

        draft.status = "posted"
        draft.posted_at = datetime.now(timezone.utc)
        if reddit_url.strip():
            draft.reddit_comment_url = reddit_url.strip()
        db.commit()

        # Audit log (best-effort)
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=user.id,
                action="draft_marked_posted",
                entity_type="comment_draft",
                entity_id=draft_id,
                details={
                    "client_id": str(client_id),
                    "avatar": avatar.reddit_username if avatar else None,
                    "reddit_url": reddit_url.strip() or None,
                    "source": "client_portal",
                },
            )
        except Exception as e:
            logger.warning("Failed to log audit event: %s", e)

        logger.info(
            "Portal: draft marked posted | draft_id=%s | user=%s | client=%s",
            draft_id, user.email, client_id,
        )

        return JSONResponse(status_code=200, content={"ok": True, "message": "Marked as posted"})

    except Exception as e:
        logger.error(
            "Portal mark-posted UNHANDLED ERROR | draft_id=%s | client_id=%s | error=%s | type=%s",
            draft_id, client_id, str(e), type(e).__name__,
        )
        db.rollback()
        return JSONResponse(status_code=500, content={"message": "Server error. Please try again."})


