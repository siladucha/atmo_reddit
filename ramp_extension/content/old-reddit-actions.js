/**
 * RAMP Extension v3 — Old Reddit Content Script Actions
 *
 * Handles DOM interaction on old.reddit.com pages.
 * Old reddit has stable, simple HTML:
 * - Plain <textarea> for comments
 * - Standard <button class="save"> for submit
 * - No Shadow DOM, no web components, no Lexical
 * - Server-rendered (no lazy loading)
 *
 * This script only activates on old.reddit.com/* URLs.
 */

(function () {
  'use strict';

  // Only run on old.reddit.com
  if (!window.location.hostname.includes('old.reddit.com')) {
    return;
  }

  console.log('[RAMP] Old Reddit content script loaded on', window.location.href);

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || !message.type) return false;

    switch (message.type) {
      case 'OLD_REDDIT_CHECK_AUTH': {
        // Check if logged in by looking for username in header
        const userLink = document.querySelector('#header-bottom-right .user a');
        if (userLink) {
          const username = userLink.textContent.trim();
          sendResponse({ logged_in: true, username });
        } else {
          // Check for login form
          const loginForm = document.querySelector('.login-form, #login-form, .login-form-side');
          sendResponse({ logged_in: !loginForm, username: null });
        }
        return false;
      }

      case 'OLD_REDDIT_CHECK_THREAD': {
        // Check if thread is locked/archived
        const locked = !!document.querySelector(
          '.locked-comment-form, .archived-infobar, ' +
          '.infobar[id*="locked"], .thing.locked'
        );
        // Also check if comment form exists at all
        const hasCommentForm = !!document.querySelector(
          '.commentarea textarea, #comment_reply_form textarea, .usertext-edit textarea'
        );
        const bodyText = document.body?.textContent || '';
        const textLocked = /this thread has been locked|comments are locked|this is an archived post/i.test(bodyText);

        sendResponse({
          locked: locked || textLocked || !hasCommentForm,
          has_form: hasCommentForm,
        });
        return false;
      }

      case 'OLD_REDDIT_INSERT_TEXT': {
        const text = message.text;
        if (!text) {
          sendResponse({ ok: false, error: 'No text provided' });
          return false;
        }

        // Find the top-level comment textarea
        // Old reddit: .commentarea > form > .usertext-edit > textarea
        const textarea = document.querySelector(
          '.commentarea .usertext-edit textarea'
        ) || document.querySelector(
          '#comment_reply_form textarea'
        ) || document.querySelector(
          'form.usertext textarea[name="text"]'
        );

        if (!textarea) {
          sendResponse({ ok: false, error: 'Comment textarea not found on page' });
          return false;
        }

        // Simple value assignment — old reddit uses standard HTML forms
        textarea.value = text;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.dispatchEvent(new Event('change', { bubbles: true }));

        // Focus for good measure
        textarea.focus();

        const charCount = textarea.value.length;
        sendResponse({ ok: charCount > 0, char_count: charCount });
        return false;
      }

      case 'OLD_REDDIT_SUBMIT': {
        // Find and click the save/submit button
        const saveBtn = document.querySelector(
          '.commentarea .usertext-buttons button.save'
        ) || document.querySelector(
          '.commentarea .usertext-buttons .btn[type="submit"]'
        ) || document.querySelector(
          '#comment_reply_form .save'
        ) || document.querySelector(
          'form.usertext button[type="submit"]'
        );

        if (!saveBtn) {
          sendResponse({ ok: false, error: 'Save/submit button not found' });
          return false;
        }

        // Click it — standard HTML button, no isTrusted issues
        saveBtn.click();
        sendResponse({ ok: true });
        return false;
      }

      case 'OLD_REDDIT_VERIFY_POSTED': {
        // After submit, old reddit reloads the page. Check if our comment is there.
        const expectedText = (message.expected_text || '').trim().substring(0, 50).toLowerCase();
        const comments = document.querySelectorAll('.usertext-body p, .md p');

        let found = false;
        let permalink = null;
        let commentId = null;

        for (const comment of comments) {
          const text = (comment.textContent || '').trim().toLowerCase();
          if (text.substring(0, 50) === expectedText) {
            found = true;
            // Try to find permalink
            const thing = comment.closest('.thing[data-fullname]');
            if (thing) {
              commentId = thing.getAttribute('data-fullname'); // t1_xxxxx
              const permLink = thing.querySelector('a.bylink[href*="/comment/"], .flat-list a[href*="/comment/"]');
              if (permLink) {
                permalink = permLink.getAttribute('href');
                if (permalink && !permalink.startsWith('http')) {
                  permalink = 'https://old.reddit.com' + permalink;
                }
              }
            }
            break;
          }
        }

        sendResponse({ found, permalink, comment_id: commentId });
        return false;
      }

      case 'GET_USERNAME': {
        // Compatibility with existing service worker
        const userEl = document.querySelector('#header-bottom-right .user a');
        sendResponse({ username: userEl ? userEl.textContent.trim() : null });
        return false;
      }

      case 'CHECK_AUTH': {
        // Compatibility: check if logged in
        const hasUser = !!document.querySelector('#header-bottom-right .user a');
        sendResponse({ expired: !hasUser });
        return false;
      }

      case 'OLD_REDDIT_SCROLL': {
        // Simulate human scrolling through subreddit feed
        const count = message.count || 3;
        const delayMs = message.delay_ms || 800;

        (async () => {
          for (let i = 0; i < count; i++) {
            // Scroll by a random amount (300-600px) to simulate scanning titles
            const scrollAmount = 300 + Math.floor(Math.random() * 300);
            window.scrollBy({ top: scrollAmount, behavior: 'smooth' });
            await new Promise(r => setTimeout(r, delayMs + Math.random() * 400));
          }
          sendResponse({ ok: true, scrolled: count });
        })();
        return true; // async response
      }

      case 'OLD_REDDIT_CLICK_THREAD': {
        // Find a thread link in the subreddit feed by thread ID and click it
        const threadId = message.thread_id;
        if (!threadId) {
          sendResponse({ found: false, error: 'No thread_id provided' });
          return false;
        }

        // Old reddit feed: each post is a .thing[data-fullname="t3_XXXXX"]
        // Thread links: a.title[href*="/comments/XXXXX/"]
        const link = document.querySelector(
          `a.title[href*="/comments/${threadId}/"]`
        ) || document.querySelector(
          `.thing[data-fullname="t3_${threadId}"] a.title`
        ) || document.querySelector(
          `a[href*="/comments/${threadId}"]`
        );

        if (link) {
          // Scroll the link into view first (human-like)
          link.scrollIntoView({ behavior: 'smooth', block: 'center' });
          setTimeout(() => {
            link.click();
            sendResponse({ found: true });
          }, 500 + Math.random() * 500);
          return true; // async response
        } else {
          sendResponse({ found: false, error: 'Thread not visible in feed' });
          return false;
        }
      }

      case 'OLD_REDDIT_SCROLL_TO_COMMENTS': {
        // Scroll down to the comment area (past the post body)
        const commentArea = document.querySelector('.commentarea') ||
                            document.querySelector('#comment_reply_form') ||
                            document.querySelector('.usertext-edit');

        if (commentArea) {
          commentArea.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else {
          // Fallback: scroll to 70% of page (comment area is usually below post)
          const targetY = document.body.scrollHeight * 0.6;
          window.scrollTo({ top: targetY, behavior: 'smooth' });
        }
        sendResponse({ ok: true });
        return false;
      }

      default:
        return false;
    }
  });

  // Auto-report username on load
  setTimeout(() => {
    const userEl = document.querySelector('#header-bottom-right .user a');
    if (userEl) {
      chrome.runtime.sendMessage({ type: 'SET_ACTIVE_USERNAME', username: userEl.textContent.trim() });
    }
  }, 2000);

})();
