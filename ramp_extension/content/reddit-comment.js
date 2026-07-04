/**
 * RAMP Extension — Reddit Comment Posting
 *
 * Posts comments to Reddit threads via DOM manipulation.
 * Uses the selector system from reddit-selectors.js (globalThis.RAMP.selectors)
 * for variant-aware element targeting.
 *
 * Exports postComment() and attaches to globalThis.RAMP.actions.
 */

const SUBMIT_TIMEOUT_MS = 30_000;
const ELEMENT_POLL_INTERVAL_MS = 300;

/**
 * Polls the DOM until an element matching the selector appears or timeout is reached.
 *
 * @param {string} selectorKey - Key for globalThis.RAMP.selectors.querySelector
 * @param {number} timeoutMs - Maximum wait time in milliseconds
 * @param {Document|Element} [root=document] - Root element to search within
 * @returns {Promise<Element|null>} - Resolved element or null on timeout
 */
function waitForElement(selectorKey, timeoutMs, root = document) {
  return new Promise((resolve) => {
    const { querySelector } = globalThis.RAMP?.selectors || {};
    if (!querySelector) {
      resolve(null);
      return;
    }

    // Check immediately
    const existing = querySelector(selectorKey, root);
    if (existing) {
      resolve(existing);
      return;
    }

    const startTime = Date.now();
    const interval = setInterval(() => {
      const el = querySelector(selectorKey, root);
      if (el) {
        clearInterval(interval);
        resolve(el);
        return;
      }
      if (Date.now() - startTime >= timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, ELEMENT_POLL_INTERVAL_MS);
  });
}

/**
 * Detect if the current thread is locked, archived, or removed.
 *
 * @returns {{blocked: boolean, reason: string|null}}
 */
function detectThreadBlocked() {
  // Shreddit: locked banner or attribute
  const lockedBanner = document.querySelector(
    '[slot="locked-banner"],' +
    'shreddit-post[locked],' +
    '[data-testid="post-locked-banner"],' +
    '.archived-infobar,' +
    '#noresults,' +
    '.removed-body'
  );
  if (lockedBanner) {
    return { blocked: true, reason: 'thread_locked' };
  }

  // Old Reddit: locked/archived indicators
  const oldLockedNotice = document.querySelector(
    '.archived-infobar, .locked-infobar, .stickied .locked-icon'
  );
  if (oldLockedNotice) {
    return { blocked: true, reason: 'thread_locked' };
  }

  // Check for "comments are locked" text
  const body = document.body?.textContent || '';
  if (/comments are locked|this thread has been locked|this is an archived post/i.test(body)) {
    return { blocked: true, reason: 'thread_locked' };
  }

  // Check for removed thread (404-like or content removed)
  if (/this post was removed|sorry, this post has been removed|page not found/i.test(body)) {
    return { blocked: true, reason: 'thread_locked' };
  }

  return { blocked: false, reason: null };
}

/**
 * Find the parent comment element for a given comment ID.
 *
 * @param {string} commentId - Reddit comment ID (without t1_ prefix)
 * @returns {Element|null}
 */
function findCommentElement(commentId) {
  // Normalize: strip t1_ prefix if present
  const bareId = commentId.replace(/^t1_/, '');

  // Shreddit: <shreddit-comment thingid="t1_xxx">
  const shredditComment = document.querySelector(
    `shreddit-comment[thingid="t1_${bareId}"]`
  );
  if (shredditComment) return shredditComment;

  // Old Reddit: <div id="thing_t1_xxx">
  const oldComment = document.querySelector(
    `#thing_t1_${bareId}, [data-fullname="t1_${bareId}"]`
  );
  if (oldComment) return oldComment;

  // Redesign: data-testid with comment id
  const redesignComment = document.querySelector(
    `[data-testid="comment-t1_${bareId}"], [id="t1_${bareId}"]`
  );
  if (redesignComment) return redesignComment;

  return null;
}

/**
 * Click the reply button on a specific comment to reveal the reply editor.
 *
 * @param {Element} commentEl - The comment element containing the reply button
 * @returns {Promise<boolean>} - true if reply editor appeared
 */
async function clickReplyButton(commentEl) {
  const { querySelector } = globalThis.RAMP?.selectors || {};
  if (!querySelector) return false;

  // Look for reply button within the comment element
  const replyBtn = querySelector('replyButton', commentEl);
  if (!replyBtn) return false;

  replyBtn.click();

  // Wait for the text area to appear within/near the comment
  const textArea = await waitForElement('textArea', 5000, commentEl);
  return textArea !== null;
}

/**
 * Set text in the comment editor, handling both textarea and contenteditable.
 *
 * @param {Element} textAreaEl - The textarea or contenteditable element
 * @param {string} text - Comment body to insert
 */
function setCommentText(textAreaEl, text) {
  if (textAreaEl.tagName === 'TEXTAREA' || textAreaEl.tagName === 'INPUT') {
    // Standard textarea: use native value setter to trigger React/framework events
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    )?.set || Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    )?.set;

    if (nativeInputValueSetter) {
      nativeInputValueSetter.call(textAreaEl, text);
    } else {
      textAreaEl.value = text;
    }

    // Dispatch events to notify React/framework of value change
    textAreaEl.dispatchEvent(new Event('input', { bubbles: true }));
    textAreaEl.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    // Contenteditable div
    textAreaEl.focus();
    textAreaEl.textContent = text;

    // Dispatch input event for frameworks listening on contenteditable
    textAreaEl.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      inputType: 'insertText',
      data: text,
    }));
  }
}

/**
 * Wait for a new comment to appear in the DOM after submission.
 * Looks for our comment text to confirm successful posting.
 *
 * @param {string} text - The comment text we posted (first 50 chars used for matching)
 * @param {number} timeoutMs - How long to wait
 * @returns {Promise<Element|null>} - The new comment element or null
 */
function waitForNewComment(text, timeoutMs) {
  return new Promise((resolve) => {
    const snippet = text.slice(0, 50).toLowerCase();
    const startTime = Date.now();

    const interval = setInterval(() => {
      // Look for comments containing our text
      const { querySelectorAll } = globalThis.RAMP?.selectors || {};
      if (querySelectorAll) {
        const commentTexts = querySelectorAll('commentText');
        for (const el of commentTexts) {
          if (el.textContent?.toLowerCase().includes(snippet)) {
            clearInterval(interval);
            resolve(el);
            return;
          }
        }
      }

      if (Date.now() - startTime >= timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, ELEMENT_POLL_INTERVAL_MS);
  });
}

/**
 * Extract the permalink from a comment element.
 *
 * @param {Element} commentEl - The comment or its text element
 * @returns {string|null}
 */
function extractPermalink(commentEl) {
  // Walk up to the comment container
  const container = commentEl.closest?.(
    'shreddit-comment, .comment, [data-testid*="comment"]'
  ) || commentEl.parentElement;

  if (!container) return null;

  // Shreddit: thingid attribute gives us the comment ID
  const thingId = container.getAttribute?.('thingid');
  if (thingId) {
    // Build permalink from current URL + comment ID
    const threadUrl = window.location.pathname.replace(/\/$/, '');
    return `${threadUrl}/${thingId.replace('t1_', '')}/`;
  }

  // Look for a permalink/timestamp link
  const permalinkLink = container.querySelector(
    'a[href*="/comment/"], a[data-click-id="timestamp"], a.bylink, a[href*="/comments/"]'
  );
  if (permalinkLink) {
    const href = permalinkLink.getAttribute('href');
    if (href) {
      // Return absolute URL
      if (href.startsWith('http')) return href;
      return `https://www.reddit.com${href}`;
    }
  }

  // Old Reddit: data-permalink attribute
  const permaAttr = container.getAttribute?.('data-permalink');
  if (permaAttr) {
    return `https://www.reddit.com${permaAttr}`;
  }

  return null;
}

/**
 * Extract the comment ID from a comment element.
 *
 * @param {Element} commentEl - The comment or its text element
 * @returns {string|null}
 */
function extractCommentId(commentEl) {
  const container = commentEl.closest?.(
    'shreddit-comment, .comment, [data-testid*="comment"]'
  ) || commentEl.parentElement;

  if (!container) return null;

  // Shreddit: thingid="t1_xxxxx"
  const thingId = container.getAttribute?.('thingid');
  if (thingId) return thingId;

  // Old Reddit: data-fullname="t1_xxxxx"
  const fullname = container.getAttribute?.('data-fullname');
  if (fullname) return fullname;

  // Redesign: id or data-testid containing t1_
  const id = container.id;
  if (id && id.startsWith('t1_')) return id;

  const testId = container.getAttribute?.('data-testid');
  if (testId) {
    const match = testId.match(/(t1_[\w]+)/);
    if (match) return match[1];
  }

  return null;
}

/**
 * Post a comment to a Reddit thread.
 *
 * @param {string} threadUrl - Reddit thread URL
 * @param {string} text - Comment body text
 * @param {string|null} replyTo - ID of comment to reply to (null = top-level)
 * @returns {Promise<{status: string, permalink: string|null, comment_id: string|null, posted_at: string|null, error_code: string|null, error_details: string|null}>}
 */
export async function postComment(threadUrl, text, replyTo = null) {
  const { querySelector } = globalThis.RAMP?.selectors || {};

  // Verify selector system is available
  if (!querySelector) {
    return {
      status: 'error',
      permalink: null,
      comment_id: null,
      posted_at: null,
      error_code: 'dom_structure_changed',
      error_details: 'RAMP selector system not available',
    };
  }

  try {
    // Step 1: Verify we're on the correct thread.
    // For MVP, the service worker navigates via chrome.tabs.update before dispatching
    // to the content script. This check is a safety fallback.
    const currentPath = window.location.pathname || '';
    const targetUrl = new URL(threadUrl, window.location.origin);
    const targetPath = targetUrl.pathname;

    if (currentPath !== '/' && targetPath && !currentPath.includes(targetPath.split('/comments/')[1]?.split('/')[0] || '___none___')) {
      // Not on the correct thread — attempt navigation as fallback
      window.location.href = threadUrl;
      await new Promise((resolve) => {
        const onLoad = () => {
          window.removeEventListener('load', onLoad);
          resolve();
        };
        if (document.readyState === 'complete') {
          resolve();
        } else {
          window.addEventListener('load', onLoad);
        }
      });
    }

    // Step 2: Check if thread is locked/archived/removed
    const blocked = detectThreadBlocked();
    if (blocked.blocked) {
      return {
        status: 'blocked',
        permalink: null,
        comment_id: null,
        posted_at: null,
        error_code: blocked.reason,
        error_details: 'Thread is locked, archived, or removed',
      };
    }

    // Step 3: If replying to a comment, find it and click reply
    let editorRoot = document;
    if (replyTo) {
      const commentEl = findCommentElement(replyTo);
      if (!commentEl) {
        return {
          status: 'error',
          permalink: null,
          comment_id: null,
          posted_at: null,
          error_code: 'dom_structure_changed',
          error_details: `Could not find comment element for reply: ${replyTo}`,
        };
      }

      const replyOpened = await clickReplyButton(commentEl);
      if (!replyOpened) {
        return {
          status: 'error',
          permalink: null,
          comment_id: null,
          posted_at: null,
          error_code: 'dom_structure_changed',
          error_details: 'Reply button not found or reply editor did not appear',
        };
      }

      editorRoot = commentEl;
    }

    // Step 4: Find the text area
    const textArea = await waitForElement('textArea', 10_000, editorRoot);
    if (!textArea) {
      return {
        status: 'error',
        permalink: null,
        comment_id: null,
        posted_at: null,
        error_code: 'dom_structure_changed',
        error_details: 'Comment text area not found',
      };
    }

    // Step 5: Set the text content
    setCommentText(textArea, text);

    // Brief delay for UI framework to process input
    await new Promise((r) => setTimeout(r, 200));

    // Step 6: Click submit button
    const submitBtn = querySelector('submitButton', editorRoot);
    if (!submitBtn) {
      return {
        status: 'error',
        permalink: null,
        comment_id: null,
        posted_at: null,
        error_code: 'dom_structure_changed',
        error_details: 'Submit button not found',
      };
    }

    submitBtn.click();

    // Step 7: Wait for submission confirmation
    const newComment = await waitForNewComment(text, SUBMIT_TIMEOUT_MS);
    if (!newComment) {
      return {
        status: 'error',
        permalink: null,
        comment_id: null,
        posted_at: null,
        error_code: 'submit_timeout',
        error_details: 'Comment did not appear within 30s after submission',
      };
    }

    // Step 8: Extract permalink and comment ID
    const permalink = extractPermalink(newComment);
    const commentId = extractCommentId(newComment);

    return {
      status: 'posted',
      permalink: permalink,
      comment_id: commentId,
      posted_at: new Date().toISOString(),
      error_code: null,
      error_details: null,
    };
  } catch (err) {
    return {
      status: 'error',
      permalink: null,
      comment_id: null,
      posted_at: null,
      error_code: 'dom_structure_changed',
      error_details: err?.message || 'Unexpected error during comment posting',
    };
  }
}

// Expose on globalThis.RAMP.actions namespace for message-based invocation
globalThis.RAMP = globalThis.RAMP || {};
globalThis.RAMP.actions = globalThis.RAMP.actions || {};
globalThis.RAMP.actions.postComment = postComment;
