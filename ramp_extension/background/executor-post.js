/**
 * RAMP Extension — Post Submission Executor (Old Reddit)
 *
 * Submits new Reddit posts via old.reddit.com/r/{subreddit}/submit
 * which has a simple form with:
 * - Title input: `input[name="title"]`  
 * - Body textarea: `textarea[name="text"]`
 * - Submit button: `button[type="submit"]` or `#newlink-submit-button`
 *
 * FLOW:
 *   1. Navigate to old.reddit.com/r/{subreddit}/submit
 *   2. Verify auth (logged in as correct user)
 *   3. Click "text" tab (ensure text post mode, not link)
 *   4. Fill title input
 *   5. Fill body textarea
 *   6. Click submit
 *   7. Wait for redirect to new post
 *   8. Extract permalink from redirected URL
 *   9. Report success
 *
 * @module background/executor-post
 */

import { getAuth } from '../shared/auth.js';

const LOG_PREFIX = '[RAMP PostExecutor]';

/**
 * Execute a post submission task on old.reddit.com.
 *
 * @param {Object} task - Task object with generated_text containing "TITLE: ...\n\n---\n\nBODY:\n..."
 * @param {number} tabId - Chrome tab ID to use
 * @returns {Promise<{success: boolean, permalink?: string, error_code?: string, error_details?: string, events?: Array}>}
 */
export async function executePostOldReddit(task, tabId) {
  const startTime = Date.now();
  const events = [];

  function emit(step, data = {}) {
    events.push({
      task_id: task.task_id,
      step,
      timestamp: new Date().toISOString(),
      ...data,
    });
  }

  try {
    // Parse title and body from generated_text
    const { title, body } = parsePostContent(task.generated_text);
    if (!title) {
      return {
        success: false,
        error_code: 'PARSE_FAILED',
        error_details: 'Could not parse title from generated_text',
        events,
      };
    }

    const subreddit = task.subreddit;
    const submitUrl = `https://old.reddit.com/r/${subreddit}/submit?selftext=true`;

    emit('NAVIGATING', { url: submitUrl });

    // Step 1: Navigate to submit page
    await chrome.tabs.update(tabId, { url: submitUrl });
    await waitForTabComplete(tabId, 15000);
    await delay(2000); // Extra wait for form render

    // Step 2: Verify auth
    emit('VERIFYING_AUTH');
    const authResult = await sendMsg(tabId, { type: 'OLD_REDDIT_CHECK_AUTH' });
    if (!authResult || !authResult.logged_in) {
      return {
        success: false,
        error_code: 'AUTH_FAILED',
        error_details: 'Not logged in on old.reddit.com submit page',
        events,
      };
    }

    // Step 3: Ensure text tab is selected (old reddit submit has text/link tabs)
    emit('SELECTING_TEXT_TAB');
    await sendMsg(tabId, { type: 'POST_SELECT_TEXT_TAB' });
    await delay(500);

    // Step 4: Fill title
    emit('FILLING_TITLE', { title_length: title.length });
    const titleResult = await sendMsg(tabId, { type: 'POST_FILL_TITLE', title });
    if (!titleResult || !titleResult.success) {
      return {
        success: false,
        error_code: 'TITLE_FILL_FAILED',
        error_details: 'Could not fill title input',
        events,
      };
    }

    await delay(300);

    // Step 5: Fill body
    emit('FILLING_BODY', { body_length: body.length });
    const bodyResult = await sendMsg(tabId, { type: 'POST_FILL_BODY', body });
    if (!bodyResult || !bodyResult.success) {
      return {
        success: false,
        error_code: 'BODY_FILL_FAILED',
        error_details: 'Could not fill body textarea',
        events,
      };
    }

    await delay(500);

    // Step 6: Submit
    emit('SUBMITTING');
    const submitResult = await sendMsg(tabId, { type: 'POST_SUBMIT' });
    if (!submitResult || !submitResult.success) {
      return {
        success: false,
        error_code: 'SUBMIT_FAILED',
        error_details: submitResult?.error || 'Submit button click failed',
        events,
      };
    }

    // Step 7: Wait for redirect (old reddit redirects to the new post on success)
    emit('WAITING_REDIRECT');
    await delay(3000);
    const redirectedTab = await chrome.tabs.get(tabId);
    const finalUrl = redirectedTab.url || '';

    // Step 8: Verify success — URL should be the new post's permalink
    // Old reddit redirects to: https://old.reddit.com/r/{sub}/comments/{id}/{slug}/
    const isPostUrl = finalUrl.includes('/comments/') && finalUrl.includes(`/r/${subreddit}`);

    if (!isPostUrl) {
      // Check for error messages on page
      const pageCheck = await sendMsg(tabId, { type: 'POST_CHECK_ERRORS' });
      const errorMsg = pageCheck?.error || 'Submit did not redirect to new post URL';
      return {
        success: false,
        error_code: 'VERIFY_FAILED',
        error_details: errorMsg,
        events,
      };
    }

    // Convert to www.reddit.com permalink for consistency
    const permalink = finalUrl
      .replace('https://old.reddit.com', 'https://www.reddit.com')
      .replace('http://old.reddit.com', 'https://www.reddit.com');

    emit('COMPLETED', { permalink, duration_ms: Date.now() - startTime });

    return {
      success: true,
      permalink,
      duration_ms: Date.now() - startTime,
      events,
    };

  } catch (err) {
    emit('ERROR', { error: err.message });
    return {
      success: false,
      error_code: 'UNEXPECTED_ERROR',
      error_details: err.message || 'Unknown error during post submission',
      duration_ms: Date.now() - startTime,
      events,
    };
  }
}

/**
 * Parse title and body from the generated_text format:
 * "TITLE: {title}\n\n---\n\nBODY:\n{body}"
 */
function parsePostContent(text) {
  if (!text) return { title: null, body: '' };

  // Try structured format first
  const titleMatch = text.match(/^TITLE:\s*(.+?)(?:\n|$)/);
  const bodyMatch = text.match(/(?:^|\n)BODY:\n([\s\S]*)/);

  if (titleMatch) {
    return {
      title: titleMatch[1].trim(),
      body: bodyMatch ? bodyMatch[1].trim() : '',
    };
  }

  // Fallback: first line is title, rest is body
  const lines = text.split('\n');
  return {
    title: lines[0].trim(),
    body: lines.slice(1).join('\n').trim(),
  };
}

// ─── Utilities ─────────────────────────────────────────────────────────────

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function sendMsg(tabId, msg) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, msg, (response) => {
      if (chrome.runtime.lastError) {
        resolve(null);
      } else {
        resolve(response);
      }
    });
  });
}

function waitForTabComplete(tabId, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;

    const listener = (id, changeInfo) => {
      if (id === tabId && changeInfo.status === 'complete') {
        if (!settled) {
          settled = true;
          chrome.tabs.onUpdated.removeListener(listener);
          resolve();
        }
      }
    };

    chrome.tabs.onUpdated.addListener(listener);

    setTimeout(() => {
      if (!settled) {
        settled = true;
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }, timeoutMs);
  });
}
