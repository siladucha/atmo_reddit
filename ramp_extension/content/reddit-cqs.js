/**
 * RAMP Extension — Reddit CQS Check (Diagnostic Probe)
 *
 * Posts "What is my CQS?" in r/WhatIsMyCQS, waits for AutoModerator reply,
 * returns the raw bot response text to the backend for normalization.
 *
 * This is a system action (diagnostic probe) — runs in a background tab,
 * does not require executor approval, and is NOT subject to content rate limits.
 *
 * Uses the selector system from reddit-selectors.js (globalThis.RAMP.selectors)
 * where applicable. Reddit's submit page has different selectors than comment posting.
 *
 * Exports postCQSCheck() and attaches to globalThis.RAMP.actions.
 */

const CQS_POST_TITLE = 'What is my CQS?';
const CQS_POST_BODY = 'What is my CQS?';
const CQS_SUBREDDIT = 'WhatIsMyCQS';
const CQS_SUBMIT_URL = `https://old.reddit.com/r/${CQS_SUBREDDIT}/submit`;

const BOT_REPLY_TIMEOUT_MS = 90_000; // 90 seconds max wait for AutoModerator
const BOT_REPLY_POLL_INTERVAL_MS = 3_000; // Check every 3 seconds
const ELEMENT_WAIT_TIMEOUT_MS = 15_000; // Wait for page elements to appear
const ELEMENT_POLL_MS = 300;
const POST_SUBMIT_WAIT_MS = 5_000; // Wait after submit for redirect

/**
 * Submit page selectors — Reddit's submit/create-post page has its own DOM structure.
 * These are separate from comment selectors since the post creation UI is different.
 */
const SUBMIT_SELECTORS = {
  shreddit: {
    // New Reddit (shreddit) post creation
    titleInput: [
      'textarea[name="title"]',
      'input[name="title"]',
      '[placeholder*="title" i]',
      'faceplate-textarea-input[name="title"]',
      'div[slot="title"] textarea',
    ],
    bodyTextArea: [
      'div[contenteditable="true"][role="textbox"]',
      'shreddit-composer textarea',
      'div[slot="rte"] div[contenteditable="true"]',
      'textarea[name="body"]',
      'div[data-lexical-editor="true"]',
    ],
    submitButton: [
      'button[type="submit"]',
      'button[slot="submit-button"]',
      'faceplate-tracker[noun="submit"] button',
      'button:has(span)',
    ],
    textTabButton: [
      'button[role="tab"][aria-label*="Text" i]',
      'button[role="tab"]:first-child',
      '[data-testid="post-type-text"]',
    ],
  },
  old: {
    titleInput: [
      '#newlink textarea[name="title"]',
      'textarea[name="title"]',
      'input[name="title"]',
    ],
    bodyTextArea: [
      '#newlink textarea[name="text"]',
      'textarea[name="text"]',
      '.usertext-edit textarea',
    ],
    submitButton: [
      '#newlink button[type="submit"]',
      'button[name="submit"]',
      '.submit button',
    ],
    textTabButton: [
      '.tabmenu a[href*="submit?selftext=true"]',
      'a.text-button',
    ],
  },
  redesign: {
    titleInput: [
      '[data-testid="post-title-input"]',
      'textarea[placeholder*="title" i]',
      'input[placeholder*="title" i]',
    ],
    bodyTextArea: [
      '[data-testid="post-text-input"] div[contenteditable]',
      'div[role="textbox"][contenteditable="true"]',
      'textarea[placeholder*="body" i]',
    ],
    submitButton: [
      '[data-testid="post-submit-button"]',
      'button[type="submit"]',
    ],
    textTabButton: [
      '[data-testid="post-type-btn-text"]',
      'button[role="tab"]:first-child',
    ],
  },
};

/**
 * Detect the active Reddit variant.
 * Mirrors the detection from reddit-selectors.js for self-contained use.
 *
 * @returns {'shreddit' | 'old' | 'redesign'}
 */
function getRedditVariant() {
  const { detectRedditVariant } = globalThis.RAMP?.selectors || {};
  if (detectRedditVariant) return detectRedditVariant();

  // Fallback: inline detection
  if (document.querySelector('shreddit-app')) return 'shreddit';
  if (document.querySelector('#header-bottom-left')) return 'old';
  return 'redesign';
}

/**
 * Query DOM using submit-page selectors with fallback chain.
 *
 * @param {'titleInput'|'bodyTextArea'|'submitButton'|'textTabButton'} key
 * @param {Document|Element} [root=document]
 * @returns {Element|null}
 */
function querySubmitSelector(key, root = document) {
  const variant = getRedditVariant();
  const chain = SUBMIT_SELECTORS[variant]?.[key];
  if (!chain) return null;

  for (const selector of chain) {
    try {
      const el = root.querySelector(selector);
      if (el) return el;
    } catch {
      // Invalid selector in this context — skip
      continue;
    }
  }
  return null;
}

/**
 * Poll for an element using submit selectors until it appears or timeout.
 *
 * @param {'titleInput'|'bodyTextArea'|'submitButton'|'textTabButton'} key
 * @param {number} timeoutMs
 * @param {Document|Element} [root=document]
 * @returns {Promise<Element|null>}
 */
function waitForSubmitElement(key, timeoutMs, root = document) {
  return new Promise((resolve) => {
    const existing = querySubmitSelector(key, root);
    if (existing) {
      resolve(existing);
      return;
    }

    const startTime = Date.now();
    const interval = setInterval(() => {
      const el = querySubmitSelector(key, root);
      if (el) {
        clearInterval(interval);
        resolve(el);
        return;
      }
      if (Date.now() - startTime >= timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, ELEMENT_POLL_MS);
  });
}

/**
 * Set text in a form field, handling both textarea and contenteditable.
 *
 * @param {Element} el - The textarea, input, or contenteditable element
 * @param {string} text - Text to insert
 */
function setFieldText(el, text) {
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    )?.set || Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    )?.set;

    if (setter) {
      setter.call(el, text);
    } else {
      el.value = text;
    }

    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else {
    // Contenteditable
    el.focus();
    el.textContent = text;
    el.dispatchEvent(new InputEvent('input', {
      bubbles: true,
      inputType: 'insertText',
      data: text,
    }));
  }
}

/**
 * Wait for the page to navigate to the created post (after submit).
 * Reddit redirects to the new post URL after successful submission.
 *
 * @param {number} timeoutMs
 * @returns {Promise<string|null>} - The post URL or null on timeout
 */
function waitForPostRedirect(timeoutMs) {
  return new Promise((resolve) => {
    const startTime = Date.now();
    const startUrl = window.location.href;

    // If already on a post page (comments URL), resolve immediately
    if (window.location.pathname.includes('/comments/')) {
      resolve(window.location.href);
      return;
    }

    const interval = setInterval(() => {
      const currentUrl = window.location.href;
      // Check if we navigated to a post page
      if (currentUrl !== startUrl && currentUrl.includes('/comments/')) {
        clearInterval(interval);
        resolve(currentUrl);
        return;
      }
      if (Date.now() - startTime >= timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, ELEMENT_POLL_MS);
  });
}

/**
 * Find the AutoModerator reply in the comments section.
 * Looks for a comment from "AutoModerator" that contains "CQS".
 *
 * @returns {string|null} - The bot reply text or null
 */
function findAutoModReply() {
  const variant = getRedditVariant();

  if (variant === 'shreddit') {
    // Shreddit: look for <shreddit-comment> with author="AutoModerator"
    const comments = document.querySelectorAll(
      'shreddit-comment[author="AutoModerator"]'
    );
    for (const comment of comments) {
      const textEl = comment.querySelector('p, [slot="comment"] p, div[id*="richtext"]');
      const text = textEl?.textContent || comment.textContent || '';
      if (/cqs/i.test(text)) return text.trim();
    }

    // Fallback: look for any comment containing "AutoModerator" as author
    const allComments = document.querySelectorAll('shreddit-comment');
    for (const comment of allComments) {
      const author = comment.getAttribute('author') || '';
      if (author.toLowerCase() === 'automoderator') {
        const body = comment.textContent || '';
        if (/cqs/i.test(body)) return body.trim();
      }
    }
  }

  if (variant === 'old') {
    // Old Reddit: look for .comment by AutoModerator
    const authorLinks = document.querySelectorAll('.comment .author');
    for (const link of authorLinks) {
      if (link.textContent?.trim().toLowerCase() === 'automoderator') {
        const commentEl = link.closest('.comment');
        const body = commentEl?.querySelector('.usertext-body, .md');
        const text = body?.textContent || '';
        if (/cqs/i.test(text)) return text.trim();
      }
    }
  }

  if (variant === 'redesign') {
    // Redesign: look for comments with author matching AutoModerator
    const authorEls = document.querySelectorAll(
      '[data-testid="comment_author_link"], a[href="/user/AutoModerator"]'
    );
    for (const authorEl of authorEls) {
      if (authorEl.textContent?.trim().toLowerCase() === 'automoderator' ||
          authorEl.getAttribute('href')?.includes('/AutoModerator')) {
        const commentEl = authorEl.closest('[data-testid*="comment"], .Comment');
        const body = commentEl?.querySelector('[data-testid="comment"] p, p');
        const text = body?.textContent || commentEl?.textContent || '';
        if (/cqs/i.test(text)) return text.trim();
      }
    }
  }

  // Generic fallback: search for any element mentioning both AutoModerator and CQS
  const bodyText = document.body?.innerHTML || '';
  const autoModMatch = bodyText.match(
    /AutoModerator[\s\S]*?((?:Your (?:current )?CQS|CQS)[^\n<]{3,200})/i
  );
  if (autoModMatch) {
    // Extract clean text from surrounding HTML
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = autoModMatch[1];
    return tempDiv.textContent?.trim() || null;
  }

  return null;
}

/**
 * Poll for AutoModerator's CQS reply in the post's comments.
 *
 * @param {number} timeoutMs - Maximum time to wait
 * @returns {Promise<string|null>} - Bot reply text or null on timeout
 */
function waitForAutoModReply(timeoutMs) {
  return new Promise((resolve) => {
    // Check immediately
    const existing = findAutoModReply();
    if (existing) {
      resolve(existing);
      return;
    }

    const startTime = Date.now();
    const interval = setInterval(() => {
      const reply = findAutoModReply();
      if (reply) {
        clearInterval(interval);
        resolve(reply);
        return;
      }
      if (Date.now() - startTime >= timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, BOT_REPLY_POLL_INTERVAL_MS);
  });
}

/**
 * Perform the CQS check flow:
 * 1. Navigate to r/WhatIsMyCQS submit page
 * 2. Fill title + body with "What is my CQS?"
 * 3. Submit the post
 * 4. Wait for AutoModerator reply (up to 90s)
 * 5. Return raw bot reply text
 *
 * @returns {Promise<{status: string, raw_output: string|null, post_url: string|null, execution_metadata: {duration_ms: number, reddit_variant: string, timestamp: string}, error_code: string|null, error_details: string|null}>}
 */
export async function postCQSCheck() {
  const startTime = Date.now();
  const variant = getRedditVariant();

  const makeResult = (status, raw_output, post_url, error_code, error_details) => ({
    status,
    raw_output,
    post_url,
    execution_metadata: {
      duration_ms: Date.now() - startTime,
      reddit_variant: variant,
      timestamp: new Date().toISOString(),
    },
    error_code,
    error_details,
  });

  try {
    // Step 1: Navigate to the submit page
    // The service worker opens this in a background tab, so we may already be there.
    // If not on the submit page, navigate.
    const currentUrl = window.location.href;
    if (!currentUrl.includes(`/r/${CQS_SUBREDDIT}/submit`) &&
        !currentUrl.includes(`/r/${CQS_SUBREDDIT.toLowerCase()}/submit`)) {
      window.location.href = CQS_SUBMIT_URL;
      // Wait for navigation to complete
      await new Promise((resolve) => {
        const onLoad = () => {
          window.removeEventListener('load', onLoad);
          resolve();
        };
        if (document.readyState === 'complete') {
          // Give extra time for React/shreddit to hydrate
          setTimeout(resolve, 2000);
        } else {
          window.addEventListener('load', onLoad);
        }
      });
    }

    // Step 2: Ensure we're on the text post tab (not link/image)
    const textTab = querySubmitSelector('textTabButton');
    if (textTab && !textTab.getAttribute('aria-selected')?.includes('true')) {
      textTab.click();
      await new Promise((r) => setTimeout(r, 500));
    }

    // Step 3: Fill in the title
    const titleInput = await waitForSubmitElement('titleInput', ELEMENT_WAIT_TIMEOUT_MS);
    if (!titleInput) {
      return makeResult('error', null, null, 'submit_failed', 'Could not find title input on submit page');
    }
    setFieldText(titleInput, CQS_POST_TITLE);
    await new Promise((r) => setTimeout(r, 300));

    // Step 4: Fill in the body
    const bodyTextArea = await waitForSubmitElement('bodyTextArea', ELEMENT_WAIT_TIMEOUT_MS);
    if (!bodyTextArea) {
      return makeResult('error', null, null, 'submit_failed', 'Could not find body text area on submit page');
    }
    setFieldText(bodyTextArea, CQS_POST_BODY);
    await new Promise((r) => setTimeout(r, 300));

    // Step 5: Submit the post
    const submitButton = await waitForSubmitElement('submitButton', ELEMENT_WAIT_TIMEOUT_MS);
    if (!submitButton) {
      return makeResult('error', null, null, 'submit_failed', 'Could not find submit button on submit page');
    }
    submitButton.click();

    // Step 6: Wait for redirect to the new post
    const postUrl = await waitForPostRedirect(POST_SUBMIT_WAIT_MS);
    if (!postUrl) {
      // Post may have been submitted but redirect didn't happen cleanly.
      // Check if we're now on a comments page.
      if (window.location.pathname.includes('/comments/')) {
        // We're on the post page — continue
      } else {
        return makeResult('error', null, null, 'submit_failed', 'Post submission did not redirect to new post');
      }
    }

    const finalPostUrl = postUrl || window.location.href;

    // Step 7: Wait for AutoModerator reply (poll up to 90 seconds)
    // Give a brief initial delay for the page to settle
    await new Promise((r) => setTimeout(r, 2000));

    const botReply = await waitForAutoModReply(BOT_REPLY_TIMEOUT_MS);

    if (!botReply) {
      return makeResult('timeout', null, finalPostUrl, null, null);
    }

    // Step 8: Return the raw bot reply
    return makeResult('completed', botReply, finalPostUrl, null, null);

  } catch (err) {
    return makeResult(
      'error',
      null,
      null,
      'submit_failed',
      err?.message || 'Unexpected error during CQS check'
    );
  }
}

// Expose on globalThis.RAMP.actions namespace for message-based invocation
globalThis.RAMP = globalThis.RAMP || {};
globalThis.RAMP.actions = globalThis.RAMP.actions || {};
globalThis.RAMP.actions.postCQSCheck = postCQSCheck;
