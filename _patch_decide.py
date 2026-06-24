"""Patch decide_hypotheses route to add confirmation limit and remove confirm_all."""
import re

filepath = "reddit_saas/app/routes/discovery.py"

with open(filepath, "r") as f:
    content = f.read()

# Replace the body of decide_hypotheses: from "# Parse form data" to end of function
old_block = '''    # Parse form data
    form = await request.form()

    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]

    # Check for "confirm all" action
    confirm_all = form.get("confirm_all") == "1"

    decisions_made = 0
    confirmed_count = 0
    rejected_count = 0
    for h in current_hypos:
        if h.status != "proposed":
            continue

        if confirm_all:
            decision = "confirm"
        else:
            decision = form.get(f"decision_{h.id}")

        if not decision:
            continue

        if decision == "confirm":
            h.status = "confirmed"
            h.decided_at = datetime.now(timezone.utc)
            decisions_made += 1
            confirmed_count += 1
        elif decision == "reject":
            reason = form.get(f"reject_reason_{h.id}", "").strip()
            h.status = "rejected"
            h.rejection_reason = reason[:500] if reason else None
            h.decided_at = datetime.now(timezone.utc)
            decisions_made += 1
            rejected_count += 1

    if decisions_made > 0:
        # Audit log
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=current_user.id,
                action="discovery_decisions_submitted",
                entity_type="discovery_session",
                entity_id=session_id,
                details={
                    "confirmed": confirmed_count,
                    "rejected": rejected_count,
                    "confirm_all": confirm_all,
                    "iteration": session.current_iteration,
                },
            )
        except Exception:
            pass

        db.commit()
        # Refresh session to get updated relationships
        db.refresh(session)
        current_hypos = [
            h for h in session.hypotheses
            if h.iteration_number == session.current_iteration
        ]

    return templates.TemplateResponse(
        request,
        "partials/discovery_results.html",
        {
            "session": session,
            "hypotheses": current_hypos,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
        },
    )'''

new_block = '''    # Parse form data
    form = await request.form()

    current_hypos = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]

    # Count already confirmed across ALL iterations (session-wide limit)
    already_confirmed = len([
        h for h in session.hypotheses if h.status == "confirmed"
    ])

    decisions_made = 0
    confirmed_count = 0
    rejected_count = 0
    limit_hit = False

    for h in current_hypos:
        if h.status != "proposed":
            continue

        decision = form.get(f"decision_{h.id}")
        if not decision:
            continue

        if decision == "confirm":
            # Enforce session-wide cap
            if already_confirmed + confirmed_count >= MAX_CONFIRMED_HYPOTHESES:
                limit_hit = True
                continue
            h.status = "confirmed"
            h.decided_at = datetime.now(timezone.utc)
            decisions_made += 1
            confirmed_count += 1
        elif decision == "reject":
            reason = form.get(f"reject_reason_{h.id}", "").strip()
            h.status = "rejected"
            h.rejection_reason = reason[:500] if reason else None
            h.decided_at = datetime.now(timezone.utc)
            decisions_made += 1
            rejected_count += 1

    if decisions_made > 0:
        # Audit log
        try:
            from app.services.audit import log_action
            log_action(
                db=db,
                user_id=current_user.id,
                action="discovery_decisions_submitted",
                entity_type="discovery_session",
                entity_id=session_id,
                details={
                    "confirmed": confirmed_count,
                    "rejected": rejected_count,
                    "limit_hit": limit_hit,
                    "iteration": session.current_iteration,
                },
            )
        except Exception:
            pass

        db.commit()
        # Refresh session to get updated relationships
        db.refresh(session)
        current_hypos = [
            h for h in session.hypotheses
            if h.iteration_number == session.current_iteration
        ]

    return templates.TemplateResponse(
        request,
        "partials/discovery_results.html",
        {
            "session": session,
            "hypotheses": current_hypos,
            "can_generate_report": SessionManager.can_generate_report(session),
            "is_max_iterations": SessionManager.is_at_max_iterations(session),
            "max_confirmed": MAX_CONFIRMED_HYPOTHESES,
            "total_confirmed": already_confirmed + confirmed_count,
            "limit_hit": limit_hit,
        },
    )'''

if old_block not in content:
    print("ERROR: old_block not found!")
    import sys; sys.exit(1)

content = content.replace(old_block, new_block)

with open(filepath, "w") as f:
    f.write(content)

print("OK — decide_hypotheses patched")
