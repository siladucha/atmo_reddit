"""GEO Brand Detection Service — detects brand and competitor mentions in LLM responses.

Uses case-insensitive word-boundary matching with optional fuzzy matching
(Levenshtein distance <= 2) for names longer than 6 characters.
"""

import re
from dataclasses import dataclass


@dataclass
class CompetitorMatch:
    competitor_id: str
    name: str
    positions: list[int]


@dataclass
class BrandDetectionResult:
    brand_found: bool
    brand_positions: list[int]
    competitors_found: list[CompetitorMatch]


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _find_word_boundary_matches(text: str, term: str) -> list[int]:
    """Find all word-boundary positions of term in text (case-insensitive)."""
    # Escape the term for regex use and do word-boundary matching
    pattern = r'\b' + re.escape(term) + r'\b'
    matches = []
    for m in re.finditer(pattern, text, re.IGNORECASE):
        matches.append(m.start())
    return matches


def _find_fuzzy_matches(text: str, term: str, max_distance: int = 2) -> list[int]:
    """Find fuzzy matches for term in text using sliding window + Levenshtein.

    Only used for terms > 6 characters. Skips if term < 4 characters.
    """
    if len(term) < 4:
        return []

    positions = []
    text_lower = text.lower()
    term_lower = term.lower()
    term_len = len(term)

    # Sliding window: check substrings of similar length (term_len +/- 2)
    for window_size in range(max(1, term_len - 2), term_len + 3):
        for i in range(len(text_lower) - window_size + 1):
            candidate = text_lower[i:i + window_size]

            # Quick filter: first char must match or distance will be too large
            if abs(len(candidate) - term_len) > max_distance:
                continue

            # Check word boundaries
            if i > 0 and text_lower[i - 1].isalnum():
                continue
            end_pos = i + window_size
            if end_pos < len(text_lower) and text_lower[end_pos].isalnum():
                continue

            dist = _levenshtein_distance(candidate, term_lower)
            if dist <= max_distance and dist > 0:  # dist > 0 to avoid exact duplicates
                positions.append(i)

    return positions


def detect_brand(
    text: str,
    brand_name: str,
    competitors: list[dict] | None = None,
) -> BrandDetectionResult:
    """Detect brand and competitor mentions in text.

    Args:
        text: The LLM response text to scan.
        brand_name: The client's brand name.
        competitors: List of competitor dicts with keys:
            - id: competitor UUID string
            - name: competitor name
            - aliases: list of alias strings

    Returns:
        BrandDetectionResult with brand_found, brand_positions, and competitors_found.
    """
    if not text or not brand_name:
        return BrandDetectionResult(brand_found=False, brand_positions=[], competitors_found=[])

    # Detect brand
    brand_positions = _find_word_boundary_matches(text, brand_name)

    # Add fuzzy matches for brand names > 6 chars
    if len(brand_name) > 6:
        fuzzy_positions = _find_fuzzy_matches(text, brand_name)
        # Merge unique positions
        all_positions = set(brand_positions) | set(fuzzy_positions)
        brand_positions = sorted(all_positions)
    elif len(brand_name) < 4:
        # Short names: exact match only (no fuzzy), already handled above
        pass

    brand_found = len(brand_positions) > 0

    # Detect competitors
    competitors_found = []
    if competitors:
        for comp in competitors:
            comp_id = comp.get("id", "")
            comp_name = comp.get("name", "")
            comp_aliases = comp.get("aliases", []) or []

            # Collect all names to match (primary + aliases)
            names_to_check = [comp_name] + comp_aliases
            all_comp_positions = set()

            for name in names_to_check:
                if not name:
                    continue

                # Word-boundary exact match
                positions = _find_word_boundary_matches(text, name)
                all_comp_positions.update(positions)

                # Fuzzy match for names > 6 chars
                if len(name) > 6:
                    fuzzy_pos = _find_fuzzy_matches(text, name)
                    all_comp_positions.update(fuzzy_pos)

            if all_comp_positions:
                competitors_found.append(CompetitorMatch(
                    competitor_id=comp_id,
                    name=comp_name,
                    positions=sorted(all_comp_positions),
                ))

    return BrandDetectionResult(
        brand_found=brand_found,
        brand_positions=brand_positions,
        competitors_found=competitors_found,
    )
