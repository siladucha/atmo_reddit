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
        // IMPORTANT: Only check the MAIN post (.thing.link) for locked class,
        // not any .thing on page (comments also have .thing class).
        // Old reddit locked indicators:
        //   - .locked-comment-form (shown instead of textarea when locked)
        //   - .archived-infobar (explicit banner)
        //   - The main post div has class "locked": .thing.link.locked
        const hasLockedForm = !!document.querySelector('.locked-comment-form');
        const hasArchivedBar = !!document.querySelector('.archived-infobar');
        const mainPostLocked = !!document.querySelector('.sitetable > .thing.link.locked, #siteTable > .thing.link.locked');

        // Check if comment form exists — broad selector to catch all old reddit layouts
        const hasCommentForm = !!document.querySelector(
          'textarea[name="text"], .commentarea textarea, ' +
          '#comment_reply_form textarea, .usertext-edit textarea'
        );

        // Text-based detection — look for Reddit's SPECIFIC lock banners only
        // These are shown in dedicated info elements, not in comment text
        const lockBanner = document.querySelector(
          '.commentarea .infobar, .commentarea .info, .commentarea .locked-banner'
        );
        let textLocked = false;
        if (lockBanner) {
          const bannerText = lockBanner.textContent || '';
          textLocked = /this thread has been locked|comments are locked|this is an archived post/i.test(bannerText);
        }
        // Also check for Reddit's dedicated lock element that appears ABOVE comments
        if (!textLocked) {
          const lockNotice = document.querySelector(
            '.comment-visits-box + .infobar, .commentarea > .infobar, ' +
            '.commentarea > .locked-infobar, [class*="lock-notice"]'
          );
          if (lockNotice) {
            textLocked = /locked|archived/i.test(lockNotice.textContent || '');
          }
        }

        const isLocked = hasLockedForm || hasArchivedBar || mainPostLocked || textLocked;

        // Safety: if textarea exists and no explicit lock form — override text_match
        // Reddit REPLACES the textarea with .locked-comment-form when truly locked.
        // If textarea is present, the thread is postable regardless of text content.
        const effectiveLocked = hasCommentForm
          ? (hasLockedForm || hasArchivedBar || mainPostLocked)  // textarea present = ignore text_match
          : isLocked;

        console.log('[RAMP] CHECK_THREAD:', {
          hasLockedForm, hasArchivedBar, mainPostLocked, textLocked,
          hasCommentForm, isLocked, effectiveLocked,
          url: window.location.href
        });

        sendResponse({
          locked: effectiveLocked,
          has_form: hasCommentForm,
          reason: effectiveLocked
            ? (hasLockedForm ? 'locked_form' : hasArchivedBar ? 'archived' : mainPostLocked ? 'post_locked_class' : 'text_match')
            : null,
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

      // ─── Post Submission Handlers (old.reddit.com/r/{sub}/submit) ───────────

      case 'POST_SELECT_TEXT_TAB': {
        // On old reddit submit page, ensure "text" tab is selected (not "link")
        const textTab = document.querySelector('#text-field, .text-button, li.text a, [id="text"]');
        if (textTab) {
          textTab.click();
        }
        // Also check for the tabmenu
        const tabMenu = document.querySelector('.tabmenu li');
        if (tabMenu) {
          const textLi = Array.from(document.querySelectorAll('.tabmenu li a'))
            .find(a => a.textContent.trim().toLowerCase() === 'text');
          if (textLi) textLi.click();
        }
        sendResponse({ success: true });
        return false;
      }

      case 'POST_FILL_TITLE': {
        const title = message.title;
        if (!title) {
          sendResponse({ success: false, error: 'No title provided' });
          return false;
        }

        // Old reddit submit: input[name="title"] or textarea[name="title"]
        const titleInput = document.querySelector(
          'input[name="title"], textarea[name="title"], #title-field textarea'
        );
        if (!titleInput) {
          sendResponse({ success: false, error: 'Title input not found on submit page' });
          return false;
        }

        titleInput.value = title;
        titleInput.dispatchEvent(new Event('input', { bubbles: true }));
        titleInput.dispatchEvent(new Event('change', { bubbles: true }));
        titleInput.focus();

        sendResponse({ success: titleInput.value.length > 0 });
        return false;
      }

      case 'POST_FILL_BODY': {
        const body = message.body || '';

        // Old reddit submit: textarea[name="text"] in the self-text form
        const bodyTextarea = document.querySelector(
          'textarea[name="text"], #text-field textarea, .usertext-edit textarea'
        );
        if (!bodyTextarea) {
          // Body might be optional for some post types, don't fail
          sendResponse({ success: true, note: 'No body textarea found (may be link post mode)' });
          return false;
        }

        bodyTextarea.value = body;
        bodyTextarea.dispatchEvent(new Event('input', { bubbles: true }));
        bodyTextarea.dispatchEvent(new Event('change', { bubbles: true }));
        bodyTextarea.focus();

        sendResponse({ success: true });
        return false;
      }

      case 'POST_SUBMIT': {
        // Click submit button on the submit form
        const submitBtn = document.querySelector(
          '#newlink [type="submit"], #newlink-submit-button, ' +
          'button[name="submit"], .submit button[type="submit"], ' +
          '#newlink .btn[type="submit"]'
        );
        if (!submitBtn) {
          sendResponse({ success: false, error: 'Submit button not found on submit page' });
          return false;
        }

        submitBtn.click();
        sendResponse({ success: true });
        return false;
      }

      case 'POST_CHECK_ERRORS': {
        // Check for error messages on submit page after failed submission
        const errorEl = document.querySelector(
          '.error, .status-msg.error, .field-error, .submit-page .error'
        );
        const ratelimit = document.querySelector('.ratelimit');
        
        let error = null;
        if (errorEl) {
          error = errorEl.textContent.trim();
        } else if (ratelimit) {
          error = 'Rate limited: ' + ratelimit.textContent.trim();
        }
        sendResponse({ error });
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
