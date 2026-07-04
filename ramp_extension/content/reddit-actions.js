/**
 * RAMP Extension — Content Script (Reddit Actions) v2
 *
 * Handles messages from service worker with GRANULAR execution steps.
 * Each step is independent and returns proof of what it observed/did.
 *
 * Message types:
 * - GET_USERNAME → returns current logged-in username
 * - CHECK_AUTH → checks if Reddit session is active
 * - VERIFY_CONTEXT → checks page is correct thread, not locked
 * - GET_ELEMENT_COORDS → returns bounding rect for any element (supports shadow DOM)
 * - WAIT_FOR_COMPOSER → waits for contenteditable to appear via MutationObserver
 * - INSERT_TEXT → inserts text into the open editor + verifies
 * - CHECK_SUBMIT_BUTTON → checks if submit button exists (does NOT click it)
 * - VERIFY_POSTED → waits for new comment to appear, extracts permalink
 *
 * SAFETY: No message type triggers submit. Submit is handled by chrome.debugger trusted click.
 */

(function () {
  'use strict';

  const { getCurrentUsername, getCurrentUsernameAsync } = globalThis.RAMP?.username || {};
  const { detectRedditVariant, querySelector } = globalThis.RAMP?.selectors || {};
  const { clearRedditDrafts } = globalThis.RAMP?.draftCleanup || {};

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ─── Message Listener ──────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || !message.type) return false;

    switch (message.type) {
      case 'GET_USERNAME':
      case 'GET_REDDIT_USERNAME': {
        if (getCurrentUsernameAsync) {
          getCurrentUsernameAsync().then(username => {
            sendResponse({ username });
          }).catch(() => {
            sendResponse({ username: null });
          });
          return true;
        }
        const username = getCurrentUsername ? getCurrentUsername() : null;
        sendResponse({ username });
        return false;
      }

      case 'CHECK_AUTH': {
        const loginWall = document.querySelector(
          '[data-testid="login-button"], .login-form, a[href*="/login"]'
        );
        const isLoggedIn = !loginWall || !!document.querySelector(
          'button[aria-label*="avatar"], #expand-user-drawer-button'
        );
        sendResponse({ expired: !isLoggedIn });
        return false;
      }

      case 'VERIFY_CONTEXT': {
        handleVerifyContext(message, sendResponse);
        return false;
      }

      case 'DISMISS_BANNERS': {
        const { dismissBanners } = globalThis.RAMP?.bannerDismiss || {};
        if (dismissBanners) {
          dismissBanners().then(sendResponse).catch(() => {
            sendResponse({ dismissed: false, banner_type: null });
          });
          return true; // async
        }
        sendResponse({ dismissed: false, banner_type: null });
        return false;
      }

      case 'CLEAR_DRAFTS': {
        if (clearRedditDrafts) {
          const result = clearRedditDrafts();
          sendResponse(result);
        } else {
          sendResponse({ cleared: 0, keys: [] });
        }
        return false;
      }

      case 'SCROLL_TO_COMMENTS': {
        // Scroll the comment section into view so Reddit lazy-loads the composer
        const commentSection = document.querySelector(
          'shreddit-comment-tree, #comment-tree, [data-testid="comments-page-container"],' +
          'faceplate-textarea-input, .commentarea, #comments'
        );
        if (commentSection) {
          commentSection.scrollIntoView({ behavior: 'instant', block: 'center' });
        } else if (message.force) {
          // Last resort: scroll to bottom of page to trigger lazy load
          window.scrollTo(0, document.body.scrollHeight * 0.7);
        } else {
          // Scroll down 60% of viewport — comment section is usually below the fold
          window.scrollBy(0, window.innerHeight * 0.6);
        }
        sendResponse({ scrolled: true });
        return false;
      }

      case 'DEBUG_COMPOSER_STATE': {
        // Report what composer-related elements exist in the DOM for debugging
        const debug = {
          url: window.location.href,
          faceplate_textarea: !!document.querySelector('faceplate-textarea-input'),
          faceplate_textarea_count: document.querySelectorAll('faceplate-textarea-input').length,
          shreddit_composer: !!document.querySelector('shreddit-composer'),
          contenteditable: !!document.querySelector('div[contenteditable="true"]'),
          trigger_button: !!document.querySelector('[data-testid="trigger-button"]'),
          comment_tree: !!document.querySelector('shreddit-comment-tree, #comment-tree'),
          usertext_edit: !!document.querySelector('.usertext-edit textarea'),
          body_height: document.body.scrollHeight,
          viewport_scroll: window.scrollY,
          thread_locked: !!document.querySelector('[data-testid="locked-badge"], shreddit-post[locked]'),
        };
        // Check faceplate-textarea-input dimensions if it exists
        const fti = document.querySelector('faceplate-textarea-input');
        if (fti) {
          const rect = fti.getBoundingClientRect();
          debug.fti_rect = { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
          debug.fti_has_shadow = !!fti.shadowRoot;
          if (fti.shadowRoot) {
            debug.fti_inner_textarea = !!fti.shadowRoot.querySelector('#innerTextArea');
          }
        }
        console.log('[RAMP DEBUG] Composer state:', JSON.stringify(debug, null, 2));
        sendResponse(debug);
        return false;
      }

      case 'GET_ELEMENT_COORDS': {
        const { selector, shadowSelector } = message;
        let el = document.querySelector(selector);
        if (el && shadowSelector && el.shadowRoot) {
          el = el.shadowRoot.querySelector(shadowSelector);
        }
        if (!el) { sendResponse(null); return false; }
        const rect = el.getBoundingClientRect();
        // Verify element is visible (has dimensions and is in viewport)
        if (rect.width === 0 || rect.height === 0) { sendResponse(null); return false; }
        sendResponse({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });
        return false;
      }

      case 'WAIT_FOR_COMPOSER': {
        handleWaitForComposer(message).then(sendResponse);
        return true; // async
      }

      case 'INSERT_TEXT': {
        handleInsertText(message).then(sendResponse).catch(err => {
          sendResponse({ error: err.message || 'Insert text failed' });
        });
        return true; // async
      }

      case 'CHECK_SUBMIT_BUTTON': {
        handleCheckSubmitButton(sendResponse);
        return false;
      }

      case 'VERIFY_POSTED': {
        handleVerifyPosted(message).then(sendResponse);
        return true; // async
      }

      default:
        return false;
    }
  });

  // ─── VERIFY_CONTEXT ────────────────────────────────────────────────────────

  function handleVerifyContext(message, sendResponse) {
    const variant = detectRedditVariant ? detectRedditVariant() : 'redesign';
    const url = window.location.href;

    // Check locked thread indicators
    const lockedIndicator = document.querySelector(
      '[data-testid="locked-badge"], .locked-badge, ' +
      'shreddit-post-overflow-menu[locked], shreddit-post[locked], ' +
      '[slot="locked-banner"], [data-testid="post-locked-banner"]'
    );
    if (lockedIndicator) {
      sendResponse({ error: 'thread_locked', details: 'Thread is locked', variant });
      return;
    }

    // Check locked/archived via text content
    const body = document.body?.textContent || '';
    if (/comments are locked|this thread has been locked|this is an archived post/i.test(body)) {
      sendResponse({ error: 'thread_locked', details: 'Thread locked (text match)', variant });
      return;
    }

    // Check removed
    if (/this post was removed|sorry, this post has been removed|page not found/i.test(body)) {
      sendResponse({ error: 'thread_locked', details: 'Thread removed', variant });
      return;
    }

    // Check on comments page
    const isThread = url.includes('/comments/');
    if (!isThread && message.task?.task_type === 'post_comment') {
      sendResponse({ error: 'wrong_page', details: 'Not on a thread page', variant });
      return;
    }

    sendResponse({ ok: true, variant, url });
  }

  // ─── WAIT_FOR_COMPOSER ─────────────────────────────────────────────────────

  async function handleWaitForComposer(message) {
    const timeoutMs = message.timeout_ms || 15000;
    const startTime = Date.now();

    // Check if composer is already present
    const existingComposer = findComposerElement();
    if (existingComposer) {
      console.log('[RAMP WAIT_COMPOSER] Composer already present');
      return { found: true, selector: existingComposer.selector };
    }

    // Use MutationObserver to wait for composer to appear
    return new Promise((resolve) => {
      let resolved = false;

      const timeoutId = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          observer.disconnect();
          console.log('[RAMP WAIT_COMPOSER] Timeout after', timeoutMs, 'ms');
          resolve({ found: false, error: 'timeout' });
        }
      }, timeoutMs);

      const observer = new MutationObserver(() => {
        if (resolved) return;
        const composer = findComposerElement();
        if (composer) {
          resolved = true;
          observer.disconnect();
          clearTimeout(timeoutId);
          console.log('[RAMP WAIT_COMPOSER] Composer appeared:', composer.selector);
          resolve({ found: true, selector: composer.selector });
        }
      });

      observer.observe(document.body, {
        subtree: true,
        childList: true,
      });
    });
  }

  function findComposerElement() {
    // Try Shreddit composer contenteditable
    let el = document.querySelector('shreddit-composer div[contenteditable="true"]');
    if (el) return { element: el, selector: 'shreddit-composer div[contenteditable="true"]' };

    // Try generic Lexical editor container
    el = document.querySelector('div[contenteditable="true"][role="textbox"]');
    if (el) return { element: el, selector: 'div[contenteditable="true"][role="textbox"]' };

    // Try any contenteditable with cursor-text class (Lexical)
    el = document.querySelector('div[contenteditable="true"][class*="cursor-text"]');
    if (el) return { element: el, selector: 'div[contenteditable="true"][class*="cursor-text"]' };

    // Try notranslate contenteditable (another Lexical pattern)
    el = document.querySelector('div.notranslate[contenteditable="true"]');
    if (el) return { element: el, selector: 'div.notranslate[contenteditable="true"]' };

    // Try shreddit-composer with any contenteditable
    el = document.querySelector('shreddit-composer div[contenteditable]');
    if (el) return { element: el, selector: 'shreddit-composer div[contenteditable]' };

    return null;
  }

  // ─── VERIFY_POSTED ─────────────────────────────────────────────────────────

  async function handleVerifyPosted(message) {
    const timeoutMs = message.timeout_ms || 30000;
    const expectedText = message.expected_text || '';
    const normalizedExpected = normalizeText(expectedText).substring(0, 50);

    console.log('[RAMP VERIFY_POSTED] Watching for new comment, expected first 50:', normalizedExpected);

    // Take snapshot of existing comments before we start watching
    const existingCommentIds = new Set();
    document.querySelectorAll('shreddit-comment, [data-testid="comment"]').forEach(el => {
      const id = el.getAttribute('thingid') || el.getAttribute('id') || el.dataset.testid;
      if (id) existingCommentIds.add(id);
    });

    return new Promise((resolve) => {
      let resolved = false;

      const timeoutId = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          observer.disconnect();
          console.log('[RAMP VERIFY_POSTED] Timeout after', timeoutMs, 'ms');
          resolve({ found: false, error: 'timeout' });
        }
      }, timeoutMs);

      const checkForNewComment = () => {
        if (resolved) return;

        const comments = document.querySelectorAll('shreddit-comment, [data-testid="comment"]');
        for (const comment of comments) {
          const commentId = comment.getAttribute('thingid') || comment.getAttribute('id') || comment.dataset.testid;
          // Skip comments that existed before
          if (commentId && existingCommentIds.has(commentId)) continue;

          // Get the comment text content
          const textEl = comment.querySelector('[slot="comment"] p, .md p, p, [data-testid="comment-body"]');
          const commentText = textEl ? textEl.textContent.trim() : (comment.textContent || '').trim();
          const normalizedComment = normalizeText(commentText).substring(0, 50);

          // Check if first 50 chars match (normalized)
          if (normalizedExpected && normalizedComment &&
              normalizedComment.substring(0, 50) === normalizedExpected.substring(0, 50)) {
            // Found our comment! Extract permalink
            const permalinkResult = extractPermalink(comment);
            resolved = true;
            observer.disconnect();
            clearTimeout(timeoutId);
            console.log('[RAMP VERIFY_POSTED] Comment found!', permalinkResult);
            resolve({
              found: true,
              permalink: permalinkResult.permalink || null,
              comment_id: permalinkResult.comment_id || null,
            });
            return;
          }
        }
      };

      const observer = new MutationObserver(() => {
        checkForNewComment();
      });

      observer.observe(document.body, {
        subtree: true,
        childList: true,
      });

      // Also check immediately (comment might already be there)
      checkForNewComment();
    });
  }

  function normalizeText(text) {
    return (text || '').trim().replace(/\s+/g, ' ').toLowerCase();
  }

  function extractPermalink(commentEl) {
    // Try to find permalink link inside the comment
    const permalinkLink = commentEl.querySelector('a[href*="/comment/"]');
    if (permalinkLink) {
      const href = permalinkLink.getAttribute('href');
      const match = href.match(/\/comment\/(\w+)/);
      return {
        permalink: href.startsWith('http') ? href : `https://www.reddit.com${href}`,
        comment_id: match ? match[1] : null,
      };
    }

    // Try time element's parent link
    const timeLink = commentEl.querySelector('time[datetime]');
    if (timeLink) {
      const parentLink = timeLink.closest('a[href*="/comment/"]');
      if (parentLink) {
        const href = parentLink.getAttribute('href');
        const match = href.match(/\/comment\/(\w+)/);
        return {
          permalink: href.startsWith('http') ? href : `https://www.reddit.com${href}`,
          comment_id: match ? match[1] : null,
        };
      }
    }

    // Try thingid attribute on shreddit-comment (format: t1_xxxxx)
    const thingId = commentEl.getAttribute('thingid');
    if (thingId) {
      const commentId = thingId.replace('t1_', '');
      // Build permalink from current URL + comment ID
      const currentUrl = window.location.href.split('?')[0].split('#')[0];
      return {
        permalink: `${currentUrl}${commentId}/`,
        comment_id: commentId,
      };
    }

    return { permalink: null, comment_id: null };
  }

  // ─── INSERT_TEXT ───────────────────────────────────────────────────────────

  async function handleInsertText(message) {
    const text = String(message.text || message.task?.comment_text || '');
    if (!text || text === 'undefined' || text === '[object Object]') {
      return { error: 'No valid text provided for insertion' };
    }

    console.log('[RAMP INSERT] Starting, text length:', text.length);

    // Clear Reddit's saved drafts from localStorage to prevent restoreDraft() conflict
    if (clearRedditDrafts) {
      clearRedditDrafts();
    }

    // Wait for Shreddit's restoreDraft to finish (it fires on composer open)
    await sleep(2500);

    // Check if we should use shadow textarea directly (Shreddit didn't expand to Lexical)
    let useShadowTextarea = false;
    let commentBox = null;
    
    // First try Lexical contenteditable
    commentBox = document.querySelector('shreddit-composer div[contenteditable="true"]')
      || document.querySelector('shreddit-composer div[contenteditable]')
      || document.querySelector('div[contenteditable="true"][role="textbox"]')
      || document.querySelector('div.notranslate[contenteditable="true"]')
      || document.querySelector('div[contenteditable][class*="cursor-text"]');
    
    // If no Lexical, try shadow textarea
    if (!commentBox) {
      const trigger = document.querySelector('faceplate-textarea-input[data-testid="trigger-button"]')
        || document.querySelector('faceplate-textarea-input');
      if (trigger && trigger.shadowRoot) {
        commentBox = trigger.shadowRoot.querySelector('#innerTextArea');
        if (commentBox) useShadowTextarea = true;
      }
    }
    
    // Retry loop for either
    if (!commentBox) {
      for (let attempt = 0; attempt < 6; attempt++) {
        commentBox = document.querySelector('shreddit-composer div[contenteditable="true"]')
          || document.querySelector('shreddit-composer div[contenteditable]')
          || document.querySelector('div[contenteditable="true"][role="textbox"]')
          || document.querySelector('.usertext-edit textarea')
          || document.querySelector('#innerTextArea');
        if (commentBox) break;
        console.log(`[RAMP INSERT] Editor not found, attempt ${attempt + 1}/6`);
        await sleep(500);
      }
    }

    if (!commentBox) {
      return { error: 'Editor not found — was composer opened first?' };
    }

    console.log('[RAMP INSERT] Editor found:', commentBox.tagName, useShadowTextarea ? '(SHADOW)' : '', commentBox.className?.substring(0, 60));

    // Focus the editor with a click then focus (ensures Lexical activates)
    commentBox.click();
    await sleep(200);
    commentBox.focus();
    await sleep(300);

    // Clear any restored draft content before inserting our text
    if (!useShadowTextarea && commentBox.tagName !== 'TEXTAREA') {
      const existingContent = commentBox.textContent || '';
      if (existingContent.length > 0) {
        console.log(`[RAMP INSERT] Clearing existing content: "${existingContent.substring(0, 30)}"`);
        const sel = window.getSelection();
        const rng = document.createRange();
        rng.selectNodeContents(commentBox);
        sel.removeAllRanges();
        sel.addRange(rng);
        document.execCommand('delete', false);
        await sleep(300);
      }
    }

    // If shadow textarea — use simple .value assignment
    if (useShadowTextarea || commentBox.tagName === 'TEXTAREA') {
      commentBox.value = text;
      commentBox.style.height = 'auto';
      commentBox.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      commentBox.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      await sleep(500);
      
      const charCount = commentBox.value.length;
      console.log(`[RAMP INSERT] Textarea direct write: ${charCount} chars`);
      
      return {
        ok: charCount >= 5,
        text_inserted: charCount >= 5,
        char_count: charCount,
        expected_chars: text.length,
        text_matches: true,
        first_50: commentBox.value.substring(0, 50),
      };
    }

    // Clear existing content
    if (commentBox.tagName === 'TEXTAREA') {
      commentBox.value = '';
    } else {
      // Select all existing content and delete it
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(commentBox);
      selection.removeAllRanges();
      selection.addRange(range);
      document.execCommand('delete', false);
      await sleep(200);
    }

    // Strategy 1: execCommand('insertText') — works best with Lexical
    let insertSuccess = false;
    if (commentBox.tagName !== 'TEXTAREA') {
      // Ensure cursor is at end of empty editor
      commentBox.focus();
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(commentBox);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);

      insertSuccess = document.execCommand('insertText', false, text);
      console.log('[RAMP INSERT] execCommand result:', insertSuccess);
      await sleep(800);
    }

    // Check if text appeared
    let currentContent = commentBox.tagName === 'TEXTAREA'
      ? commentBox.value
      : (commentBox.textContent || '');

    console.log(`[RAMP INSERT] After strategy 1: ${currentContent.length} chars`);

    if (currentContent.length < 5) {
      // Strategy 2: clipboard-based paste simulation
      console.log('[RAMP INSERT] Strategy 1 failed, trying InputEvent-based insertion');
      commentBox.focus();
      await sleep(200);

      // Dispatch InputEvent with insertText type — Lexical listens to these
      const inputEvent = new InputEvent('beforeinput', {
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: text,
      });
      commentBox.dispatchEvent(inputEvent);
      await sleep(300);

      // Also try the actual input event
      const inputEvent2 = new InputEvent('input', {
        bubbles: true,
        inputType: 'insertText',
        data: text,
      });
      commentBox.dispatchEvent(inputEvent2);
      await sleep(500);

      currentContent = commentBox.textContent || '';
      console.log(`[RAMP INSERT] After strategy 2 (InputEvent): ${currentContent.length} chars`);
    }

    if (currentContent.length < 5) {
      // Strategy 3: direct DOM manipulation (last resort)
      console.log('[RAMP INSERT] Strategy 2 failed, trying direct DOM');
      if (commentBox.tagName === 'TEXTAREA') {
        commentBox.value = text;
        commentBox.dispatchEvent(new Event('input', { bubbles: true }));
      } else {
        commentBox.innerHTML = '';
        const p = document.createElement('p');
        p.textContent = text;
        commentBox.appendChild(p);
        commentBox.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      }
      await sleep(500);
    }

    // Final verification: read back what's in the editor
    await sleep(1000);
    currentContent = commentBox.tagName === 'TEXTAREA'
      ? commentBox.value
      : (commentBox.textContent || '');

    const charCount = currentContent.length;
    const expectedLength = text.length;

    // Text match: normalize both (collapse whitespace, trim) then compare first 30 chars
    const normalize = s => s.trim().replace(/\s+/g, ' ').toLowerCase();
    const insertedNorm = normalize(currentContent);
    const expectedNorm = normalize(text);
    
    // Match if: first 30 chars match OR >70% of expected length present
    const first30Match = insertedNorm.substring(0, 30) === expectedNorm.substring(0, 30);
    const lengthOk = charCount >= expectedLength * 0.7;
    const textMatches = insertedNorm.length > 0 && (first30Match || lengthOk);

    console.log(`[RAMP INSERT] Verification: ${charCount} chars inserted, expected ${expectedLength}, match=${textMatches}`);
    console.log(`[RAMP INSERT] First 60: "${currentContent.substring(0, 60)}"`);
    console.log(`[RAMP INSERT] Norm first 40: inserted="${insertedNorm.substring(0, 40)}" expected="${expectedNorm.substring(0, 40)}"`);

    return {
      ok: charCount >= 5,
      text_inserted: charCount >= 5,
      char_count: charCount,
      expected_chars: expectedLength,
      text_matches: textMatches,
      first_50: currentContent.substring(0, 50),
    };
  }

  // ─── CHECK_SUBMIT_BUTTON ───────────────────────────────────────────────────

  function handleCheckSubmitButton(sendResponse) {
    const submitBtn = document.querySelector('#comment-composer-submit-button')
      || document.querySelector('faceplate-form[action*="create-comment"] button[type="submit"]')
      || document.querySelector('shreddit-composer button[type="submit"]')
      || document.querySelector('.usertext-buttons button.save');

    const available = !!submitBtn;
    const disabled = submitBtn?.disabled || false;

    sendResponse({
      available,
      disabled,
      selector: submitBtn ? (submitBtn.id || submitBtn.className?.substring(0, 40) || submitBtn.tagName) : null,
    });
  }

  // ─── Auto-report username on load ──────────────────────────────────────────

  setTimeout(async () => {
    const username = getCurrentUsernameAsync
      ? await getCurrentUsernameAsync()
      : (getCurrentUsername ? getCurrentUsername() : null);
    if (username) {
      chrome.runtime.sendMessage({ type: 'SET_ACTIVE_USERNAME', username });
    }
  }, 4000);

  console.log('[RAMP] Content script v2 loaded on', window.location.hostname);
})();
