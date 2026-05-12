"""Text sanitizer for Reddit-safe comment output.

Normalizes LLM-generated text to appear as natural human-typed content on Reddit.
Reddit interprets text as Markdown, so any formatting characters in the raw text
will render as bold, italic, code, blockquotes, etc. — making comments look
non-human and risking account suspension.

This module provides a single entry point: sanitize_for_reddit(text) that strips
all Markdown-significant characters and normalizes Unicode to ASCII equivalents.
"""

import re
import logging

logger = logging.getLogger(__name__)


def sanitize_for_reddit(text: str) -> str:
    """Sanitize LLM output for safe Reddit posting as plain text.

    Applies transformations in a specific order to avoid conflicts:
    1. Strip zero-width / invisible Unicode characters
    2. Normalize Unicode punctuation to ASCII
    3. Remove Markdown formatting syntax
    4. Normalize whitespace
    5. Final cleanup

    Args:
        text: Raw LLM output text.

    Returns:
        Sanitized plain text safe for Reddit posting.
        Returns empty string if input is None or empty.
    """
    if not text:
        return ""

    result = text

    # --- Step 1: Remove invisible Unicode characters ---
    # Zero-width spaces, joiners, BOM, soft hyphens, etc.
    result = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u180e]', '', result)

    # --- Step 2: Normalize Unicode punctuation to ASCII ---
    # Smart/curly quotes → straight quotes
    result = result.replace('\u201c', '"')  # "
    result = result.replace('\u201d', '"')  # "
    result = result.replace('\u2018', "'")  # '
    result = result.replace('\u2019', "'")  # '
    result = result.replace('\u201a', "'")  # ‚
    result = result.replace('\u201b', "'")  # ‛
    result = result.replace('\u201e', '"')  # „
    result = result.replace('\u201f', '"')  # ‟

    # Em-dash → comma or hyphen (context-dependent, use hyphen as safe default)
    result = result.replace('\u2014', ' - ')  # —
    result = result.replace('\u2013', '-')     # – (en-dash)

    # Ellipsis character → three dots
    result = result.replace('\u2026', '...')

    # Non-breaking space → regular space
    result = result.replace('\u00a0', ' ')

    # Other special spaces (thin space, hair space, etc.)
    result = re.sub(r'[\u2000-\u200a]', ' ', result)

    # --- Step 3: Remove Markdown formatting syntax ---
    # Bold/italic: **text** or __text__ → text
    result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
    result = re.sub(r'__(.+?)__', r'\1', result)

    # Italic: *text* or _text_ → text (but not mid-word underscores like variable_name)
    result = re.sub(r'(?<!\w)\*([^*\n]+?)\*(?!\w)', r'\1', result)
    result = re.sub(r'(?<!\w)_([^_\n]+?)_(?!\w)', r'\1', result)

    # Strikethrough: ~~text~~ → text
    result = re.sub(r'~~(.+?)~~', r'\1', result)

    # Inline code: `text` → text
    result = re.sub(r'`([^`\n]+?)`', r'\1', result)

    # Code blocks: ```...``` → content
    result = re.sub(r'```[\s\S]*?```', '', result)

    # Blockquotes: lines starting with >
    result = re.sub(r'^>\s?', '', result, flags=re.MULTILINE)

    # Headers: lines starting with # ## ### etc.
    result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)

    # Markdown links: [text](url) → text
    result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', result)

    # Bullet lists: lines starting with - or * followed by space
    result = re.sub(r'^[\-\*]\s+', '', result, flags=re.MULTILINE)

    # Numbered lists: lines starting with 1. 2. etc.
    result = re.sub(r'^\d+\.\s+', '', result, flags=re.MULTILINE)

    # Remaining standalone asterisks that might trigger formatting
    # Only remove if they appear at word boundaries (not in mid-word like "f*ck")
    result = re.sub(r'(?<!\w)\*(?!\w)', '', result)

    # --- Step 4: Normalize whitespace ---
    # Collapse multiple newlines to single newline
    result = re.sub(r'\n{3,}', '\n\n', result)

    # Strip trailing whitespace from each line
    result = re.sub(r'[ \t]+$', '', result, flags=re.MULTILINE)

    # Collapse multiple spaces (but not newlines)
    result = re.sub(r'[^\S\n]{2,}', ' ', result)

    # --- Step 5: Final cleanup ---
    result = result.strip()

    # If sanitization produced empty string from non-empty input, return original
    if not result and text.strip():
        logger.warning("Sanitization produced empty output from non-empty input, returning original")
        return text.strip()

    return result
