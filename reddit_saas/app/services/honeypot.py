"""Honeypot anti-spam protection.

Hidden form field that real users never fill in, but bots auto-populate.
If `_gotcha` has any value -> it's a bot -> silently reject.

Usage in route handlers:
    from app.services.honeypot import is_bot_submission

    form = await request.form()
    if is_bot_submission(form):
        # Return success-looking response (don't reveal detection)
        return RedirectResponse(url="/thank-you", status_code=303)
"""

import logging
from typing import Union

from starlette.datastructures import FormData

logger = logging.getLogger(__name__)


def is_bot_submission(form: Union[FormData, dict]) -> bool:
    """Check if form submission is from a bot via honeypot field.

    Returns True if the hidden `_gotcha` field is filled (bot detected).
    Real users never see or fill this field.
    """
    gotcha_value = ""
    if isinstance(form, dict):
        gotcha_value = form.get("_gotcha", "")
    else:
        gotcha_value = form.get("_gotcha", "")

    if gotcha_value:
        logger.warning(
            "Honeypot triggered: _gotcha field filled with %d chars",
            len(str(gotcha_value)),
        )
        return True
    return False
