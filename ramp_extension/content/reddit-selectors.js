/**
 * RAMP Extension — Reddit Variant Detection & Selector Fallback Chains
 *
 * Detects which Reddit UI variant is active (shreddit, old, redesign)
 * and provides selector helpers that try each fallback in order.
 *
 * If all selectors fail for a given key, helpers return null.
 * Caller is responsible for reporting `dom_structure_changed` when appropriate.
 *
 * Exports as ES modules (for testing/bundling) AND attaches to
 * globalThis.RAMP namespace (for content script inter-file access).
 */

/**
 * Detect the active Reddit UI variant.
 * @returns {'shreddit' | 'old' | 'redesign'}
 */
export function detectRedditVariant() {
  if (document.querySelector('shreddit-app')) return 'shreddit';
  if (document.querySelector('#header-bottom-left')) return 'old';
  return 'redesign';
}

/**
 * Selector fallback chains per Reddit variant and action type.
 * Each key maps to an array of CSS selectors tried in order.
 */
export const SELECTORS = {
  shreddit: {
    replyButton: ['[slot="reply-button"]', 'button[data-testid="reply"]'],
    textArea: ['shreddit-composer textarea', 'div[contenteditable="true"]'],
    submitButton: ['button[type="submit"][slot="submit-button"]', 'button[slot="submit"]'],
    username: ['faceplate-tracker[source="profile_menu"] span', '#email-collection-tooltip-id'],
    commentText: ['shreddit-comment p', '[slot="comment"] p'],
    karmaDisplay: ['[data-testid="karma"]', '#karma'],
  },
  old: {
    replyButton: ['.reply-button', 'a.reply-button'],
    textArea: ['.usertext-edit textarea', '#comment_reply_form textarea'],
    submitButton: ['.save', 'button.save'],
    username: ['.user a', '#header-bottom-right .user a'],
    commentText: ['.usertext-body p', '.md p'],
    karmaDisplay: ['.karma', '.comment-karma'],
  },
  redesign: {
    replyButton: ['[data-testid="comment-reply-button"]'],
    textArea: ['[data-testid="comment-composer"] div[contenteditable]'],
    submitButton: ['[data-testid="comment-submit-button"]'],
    username: ['[data-testid="user-drawer-name"]', '#USER_DROPDOWN_ID span'],
    commentText: ['[data-testid="comment"] p'],
    karmaDisplay: ['[data-testid="karma"]'],
  },
};

/**
 * Try each selector in the fallback chain for the current variant.
 * Returns the first matching element, or null if all fail.
 *
 * @param {string} selectorKey - Key into the SELECTORS map (e.g. 'replyButton')
 * @param {Document|Element} [root=document] - Root element to query within
 * @returns {Element|null}
 */
export function querySelector(selectorKey, root = document) {
  const variant = detectRedditVariant();
  const chain = SELECTORS[variant]?.[selectorKey];

  if (!chain) return null;

  for (const selector of chain) {
    const el = root.querySelector(selector);
    if (el) return el;
  }

  return null;
}

/**
 * Try each selector in the fallback chain for the current variant.
 * Returns all matching elements across the chain, or an empty NodeList-like array if all fail.
 *
 * @param {string} selectorKey - Key into the SELECTORS map (e.g. 'commentText')
 * @param {Document|Element} [root=document] - Root element to query within
 * @returns {Element[]}
 */
export function querySelectorAll(selectorKey, root = document) {
  const variant = detectRedditVariant();
  const chain = SELECTORS[variant]?.[selectorKey];

  if (!chain) return [];

  for (const selector of chain) {
    const elements = root.querySelectorAll(selector);
    if (elements.length > 0) return Array.from(elements);
  }

  return [];
}

// Expose on globalThis.RAMP for content script inter-file access
globalThis.RAMP = globalThis.RAMP || {};
globalThis.RAMP.selectors = {
  detectRedditVariant,
  SELECTORS,
  querySelector,
  querySelectorAll,
};
