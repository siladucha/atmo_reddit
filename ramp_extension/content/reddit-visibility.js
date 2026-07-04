/**
 * RAMP Extension — Reddit Submission Visibility Check (Diagnostic Probe)
 *
 * Checks if a given post is visible in a subreddit's /new feed.
 * Used to detect global shadowbans: if a post exists on the user's profile
 * but does NOT appear in the subreddit's /new listing, the account is
 * likely shadowbanned.
 *
 * This is a system action (diagnostic probe) — runs in a background tab,
 * does not require executor approval, and is NOT subject to content rate limits.
 *
 * Exports checkSubmissionVisibility() and attaches to globalThis.RAMP.actions.
 */

const FEED_LOAD_TIMEOUT_MS = 15_000; // Max wait for /new feed to load
const FEED_POLL_INTERVAL_MS = 500; // Check every 500ms for feed posts

/**
 * Selectors for post links/elements in the /new feed, per Reddit variant.
 * Each variant has different DOM structures for listing posts.
 */
const FEED_POST_SELECTORS = {
  shreddit: [
    'shreddit-post',
    'article[data-testid="post-container"]',
    'div[data-testid="post-container"]',
    'faceplate-tracker[source="post"]',
  ],
  old: [
    '#siteTable .thing[data-fullname]',
    '#siteTable .link',
    '.linklisting .thing',
  ],
  redesign: [
    '[data-testid="post-container"]',
    'div[data-click-id="body"]',
    'article',
  ],
};

/**
 * Selectors for links within feed posts that contain the post URL/permalink.
 */
const FEED_LINK_SELECTORS = {
  shreddit: [
    'a[slot="full-post-link"]',
    'a[href*="/comments/"]',
    'a[data-click-id="body"]',
  ],
  old: [
    'a.title',
    'a.bylink',
    'a[data-event-action="title"]',
    'a.comments',
  ],
  redesign: [
    'a[data-click-id="body"]',
    'a[href*="/comments/"]',
    'a[data-testid="post-title"]',
  ],
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
 * Extract the Reddit post ID from a URL.
 * Reddit post URLs contain the ID in the path: /comments/{postId}/
 *
 * @param {string} url - Full Reddit post URL
 * @returns {string|null} - The post ID (e.g., "abc123") or null
 */
export function extractPostId(url) {
  if (!url) return null;

  // Match /comments/{postId}/ or /comments/{postId}
  const match = url.match(/\/comments\/([a-z0-9]+)/i);
  return match ? match[1] : null;
}

/**
 * Wait for feed posts to appear in the DOM.
 * Polls until at least one post element is found or timeout.
 *
 * @param {number} timeoutMs - Maximum time to wait
 * @returns {Promise<Element[]>} - Array of post elements (may be empty on timeout)
 */
function waitForFeedPosts(timeoutMs) {
  return new Promise((resolve) => {
    const variant = getRedditVariant();
    const selectors = FEED_POST_SELECTORS[variant] || [];

    // Check immediately
    for (const selector of selectors) {
      const posts = document.querySelectorAll(selector);
      if (posts.length > 0) {
        resolve(Array.from(posts));
        return;
      }
    }

    const startTime = Date.now();
    const interval = setInterval(() => {
      for (const selector of selectors) {
        const posts = document.querySelectorAll(selector);
        if (posts.length > 0) {
          clearInterval(interval);
          resolve(Array.from(posts));
          return;
        }
      }
      if (Date.now() - startTime >= timeoutMs) {
        clearInterval(interval);
        resolve([]);
      }
    }, FEED_POLL_INTERVAL_MS);
  });
}

/**
 * Scan all visible posts in the feed and check if any match the target post ID.
 * Looks at links within each post element for /comments/{postId}/.
 *
 * @param {Element[]} postElements - Array of post container elements
 * @param {string} targetPostId - The post ID to look for
 * @returns {{found: boolean, checked: number}}
 */
function scanFeedForPost(postElements, targetPostId) {
  const variant = getRedditVariant();
  const linkSelectors = FEED_LINK_SELECTORS[variant] || [];
  let checked = 0;

  for (const postEl of postElements) {
    checked++;

    // Check shreddit-post permalink attribute directly
    if (variant === 'shreddit') {
      const permalink = postEl.getAttribute('permalink') ||
                        postEl.getAttribute('content-href') ||
                        postEl.getAttribute('post-url');
      if (permalink && permalink.includes(`/comments/${targetPostId}`)) {
        return { found: true, checked };
      }
    }

    // Check old Reddit data attributes
    if (variant === 'old') {
      const permalink = postEl.getAttribute('data-permalink') ||
                        postEl.getAttribute('data-url');
      if (permalink && permalink.includes(`/comments/${targetPostId}`)) {
        return { found: true, checked };
      }
    }

    // Search links within the post element
    for (const linkSelector of linkSelectors) {
      const links = postEl.querySelectorAll(linkSelector);
      for (const link of links) {
        const href = link.getAttribute('href') || '';
        if (href.includes(`/comments/${targetPostId}`)) {
          return { found: true, checked };
        }
      }
    }

    // Fallback: check all anchor tags in the post for the post ID
    const allLinks = postEl.querySelectorAll('a[href*="/comments/"]');
    for (const link of allLinks) {
      const href = link.getAttribute('href') || '';
      if (href.includes(`/comments/${targetPostId}`)) {
        return { found: true, checked };
      }
    }
  }

  return { found: false, checked };
}

/**
 * Check if a post is visible in a subreddit's /new feed.
 *
 * Strategy:
 * 1. Navigate to https://www.reddit.com/r/{subreddit}/new/
 * 2. Wait for feed posts to appear (up to 15s)
 * 3. Scan all post links for one matching the postUrl (by post ID)
 * 4. Return result with visibility status
 *
 * @param {string} postUrl - The Reddit post URL to check visibility for
 * @param {string} subreddit - The subreddit name (without r/ prefix)
 * @returns {Promise<{status: string, visible: boolean, checked_posts: number, execution_metadata: {duration_ms: number, reddit_variant: string, timestamp: string}, error_code: string|null, error_details: string|null}>}
 */
export async function checkSubmissionVisibility(postUrl, subreddit) {
  const startTime = Date.now();
  const variant = getRedditVariant();

  const makeResult = (status, visible, checked_posts, error_code, error_details) => ({
    status,
    visible,
    checked_posts,
    execution_metadata: {
      duration_ms: Date.now() - startTime,
      reddit_variant: variant,
      timestamp: new Date().toISOString(),
    },
    error_code,
    error_details,
  });

  try {
    // Validate inputs
    if (!postUrl) {
      return makeResult('error', false, 0, 'invalid_input', 'postUrl is required');
    }
    if (!subreddit) {
      return makeResult('error', false, 0, 'invalid_input', 'subreddit is required');
    }

    // Extract post ID from the URL
    const targetPostId = extractPostId(postUrl);
    if (!targetPostId) {
      return makeResult('error', false, 0, 'invalid_input', 'Could not extract post ID from postUrl');
    }

    // Step 1: Navigate to the subreddit's /new feed
    const newFeedUrl = `https://www.reddit.com/r/${subreddit}/new/`;
    const currentUrl = window.location.href;

    if (!currentUrl.includes(`/r/${subreddit}/new`) &&
        !currentUrl.includes(`/r/${subreddit.toLowerCase()}/new`)) {
      window.location.href = newFeedUrl;
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

    // Step 2: Wait for feed posts to appear
    const posts = await waitForFeedPosts(FEED_LOAD_TIMEOUT_MS);

    if (posts.length === 0) {
      return makeResult('error', false, 0, 'feed_load_timeout', 'Feed posts did not appear within 15 seconds');
    }

    // Step 3: Scan all posts for the target post ID
    const { found, checked } = scanFeedForPost(posts, targetPostId);

    // Step 4: Return result
    return makeResult('completed', found, checked, null, null);

  } catch (err) {
    return makeResult(
      'error',
      false,
      0,
      'unexpected_error',
      err?.message || 'Unexpected error during visibility check'
    );
  }
}

// Expose on globalThis.RAMP.actions namespace for message-based invocation
globalThis.RAMP = globalThis.RAMP || {};
globalThis.RAMP.actions = globalThis.RAMP.actions || {};
globalThis.RAMP.actions.checkSubmissionVisibility = checkSubmissionVisibility;
