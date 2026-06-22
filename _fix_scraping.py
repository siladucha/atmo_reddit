"""Patch scraping.py to add immediate disable for 403/404 errors."""
import re

filepath = "/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/tasks/scraping.py"

with open(filepath, "r") as f:
    content = f.read()

# The old block we want to replace (line 511 onwards)
old_block = """    except Exception as e:
        error_str = str(e)

        # Update last_scraped_at even on failure so admin UI reflects the attempt
        try:
            db.rollback()
            sub_record = db.query(Subreddit).filter(Subreddit.id == subreddit_uuid).first()
            if sub_record:
                sub_record.last_scraped_at = datetime.now(timezone.utc)
                subreddit_name = sub_record.subreddit_name

                # --- Consecutive failure tracking + auto-disable ---
                sub_record.consecutive_failures = (sub_record.consecutive_failures or 0) + 1
                from app.services.settings import get_setting_int
                max_failures = get_setting_int(db, "scrape_max_consecutive_failures", 5)

                if sub_record.consecutive_failures >= max_failures:
                    sub_record.is_active = False
                    sub_record.disabled_reason = f"Auto-disabled after {sub_record.consecutive_failures} consecutive failures. Last error: {error_str[:200]}"
                    sub_record.disabled_at = datetime.now(timezone.utc)
                    logger.warning(
                        "scrape_subreddit_shared: AUTO-DISABLED r/%s after %d consecutive failures (error: %s)",
                        subreddit_name, sub_record.consecutive_failures, error_str[:100],
                    )"""

new_block = """    except Exception as e:
        error_str = str(e)

        # Classify error: permanent (403/404) vs transient
        is_permanent = isinstance(e, (Forbidden, NotFound))
        if is_permanent:
            if isinstance(e, Forbidden):
                disable_reason = f"Subreddit returned 403 Forbidden (private, quarantined, or banned): {error_str[:150]}"
            else:
                disable_reason = f"Subreddit returned 404 Not Found (deleted or never existed): {error_str[:150]}"

        # Update last_scraped_at even on failure so admin UI reflects the attempt
        try:
            db.rollback()
            sub_record = db.query(Subreddit).filter(Subreddit.id == subreddit_uuid).first()
            if sub_record:
                sub_record.last_scraped_at = datetime.now(timezone.utc)
                subreddit_name = sub_record.subreddit_name

                if is_permanent:
                    # Immediate disable — no point retrying private/deleted subreddits
                    sub_record.is_active = False
                    sub_record.consecutive_failures = (sub_record.consecutive_failures or 0) + 1
                    sub_record.disabled_reason = disable_reason
                    sub_record.disabled_at = datetime.now(timezone.utc)
                    logger.warning(
                        "scrape_subreddit_shared: IMMEDIATE DISABLE r/%s — %s",
                        subreddit_name, disable_reason[:100],
                    )
                else:
                    # --- Consecutive failure tracking + auto-disable ---
                    sub_record.consecutive_failures = (sub_record.consecutive_failures or 0) + 1
                    from app.services.settings import get_setting_int
                    max_failures = get_setting_int(db, "scrape_max_consecutive_failures", 5)

                    if sub_record.consecutive_failures >= max_failures:
                        sub_record.is_active = False
                        sub_record.disabled_reason = f"Auto-disabled after {sub_record.consecutive_failures} consecutive failures. Last error: {error_str[:200]}"
                        sub_record.disabled_at = datetime.now(timezone.utc)
                        logger.warning(
                            "scrape_subreddit_shared: AUTO-DISABLED r/%s after %d consecutive failures (error: %s)",
                            subreddit_name, sub_record.consecutive_failures, error_str[:100],
                        )"""

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open(filepath, "w") as f:
        f.write(content)
    print("SUCCESS: Replaced block")
else:
    print("ERROR: Old block not found!")
    # Debug: show around line 511
    lines = content.split('\n')
    for i in range(510, 535):
        print(f"{i+1}: {repr(lines[i])}")
