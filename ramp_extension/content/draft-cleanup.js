/**
 * RAMP Extension — Reddit localStorage Draft Cleanup
 *
 * Scans localStorage for Reddit draft-related keys and removes them.
 * This prevents Reddit's restoreDraft() from overwriting inserted text
 * when the Lexical/Shreddit composer opens.
 *
 * Patterns removed (case-insensitive):
 * - Keys containing "draft" (covers draft-, comment_draft:, saved-draft)
 * - Keys containing "comment-draft"
 * - Keys containing "shreddit-composer"
 * - Keys containing "richtext" (Reddit rich text editor state)
 * - Keys containing "lexical" (Facebook Lexical editor state)
 * - Keys starting with "t3_" or "t1_" followed by draft indicators
 *
 * Exports as ES modules (for testing/bundling) AND attaches to
 * globalThis.RAMP namespace (for content script inter-file access).
 */

/**
 * Draft key patterns to match (case-insensitive).
 * Order doesn't matter — all are checked against every key.
 */
const DRAFT_PATTERNS = [
  /draft/i,
  /comment-draft/i,
  /shreddit-composer/i,
  /richtext/i,
  /lexical/i,
  /^t[13]_.*(?:draft|comment|reply|compose)/i,
];

/**
 * Scan all localStorage keys and remove those matching Reddit draft patterns.
 * Called BEFORE opening the composer to prevent restoreDraft() conflicts.
 *
 * @returns {{ cleared: number, keys: string[] }} Count and list of removed keys.
 */
export function clearRedditDrafts() {
  const result = { cleared: 0, keys: [] };

  try {
    if (typeof localStorage === 'undefined' || !localStorage) {
      console.log('[RAMP DRAFTS] localStorage not available');
      return result;
    }

    const keysToRemove = [];

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key) continue;

      const matches = DRAFT_PATTERNS.some(pattern => pattern.test(key));
      if (matches) {
        keysToRemove.push(key);
      }
    }

    for (const key of keysToRemove) {
      try {
        localStorage.removeItem(key);
        result.keys.push(key);
        result.cleared++;
      } catch (e) {
        // Some keys may be read-only or throw in restricted contexts
        console.log(`[RAMP DRAFTS] Could not remove key "${key}":`, e.message);
      }
    }

    if (result.cleared > 0) {
      console.log(`[RAMP DRAFTS] Cleared ${result.cleared} draft key(s):`, result.keys);
    }
  } catch (e) {
    console.log('[RAMP DRAFTS] Error during draft cleanup:', e.message);
  }

  return result;
}

// Expose on globalThis.RAMP for content script inter-file access
globalThis.RAMP = globalThis.RAMP || {};
globalThis.RAMP.draftCleanup = {
  clearRedditDrafts,
};
