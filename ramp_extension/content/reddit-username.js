/**
 * RAMP Extension — Reddit Username Detection
 *
 * Detects the currently logged-in Reddit account username.
 * Uses the selector system from reddit-selectors.js (globalThis.RAMP.selectors)
 * with additional fallback strategies per variant.
 *
 * Exports getCurrentUsername() and attaches to globalThis.RAMP.username.
 */

/**
 * Extract a bare username from text that might include "u/" prefix,
 * whitespace, or other noise.
 *
 * @param {string} raw - Raw text that may contain a username
 * @returns {string|null} - Clean username or null if empty/invalid
 */
function cleanUsername(raw) {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;

  // Strip leading "u/" or "/u/" prefix
  const cleaned = trimmed.replace(/^\/?(u\/)/i, '');
  // Username must be 3-20 chars, alphanumeric + underscores + hyphens
  if (/^[\w-]{3,20}$/.test(cleaned)) {
    return cleaned;
  }
  return null;
}

/**
 * Extract username from an href containing /user/ path.
 *
 * @param {string} href - URL string (absolute or relative)
 * @returns {string|null}
 */
function extractUsernameFromHref(href) {
  if (!href) return null;
  const match = href.match(/\/user\/([\w-]{3,20})\/?/);
  return match ? match[1] : null;
}

/**
 * Strategy: Try the selector system first (variant-aware username selectors).
 * @returns {string|null}
 */
function trySelectors() {
  const { querySelector } = globalThis.RAMP?.selectors || {};
  if (!querySelector) return null;

  const el = querySelector('username');
  if (!el) return null;

  // First try: element might be a link — check href for /user/ pattern
  const href = el.getAttribute?.('href') || el.closest?.('a')?.getAttribute?.('href');
  const fromHref = extractUsernameFromHref(href);
  if (fromHref) return fromHref;

  // Second try: text content of the element
  return cleanUsername(el.textContent);
}

/**
 * Strategy for shreddit variant: look for profile links containing /user/.
 * @returns {string|null}
 */
function tryShreddit() {
  // 1. shreddit-app element often has user-related attributes
  const shredditApp = document.querySelector('shreddit-app');
  if (shredditApp) {
    // Try various attribute names Reddit has used
    for (const attr of ['user', 'logged-in-user', 'current-user', 'data-user']) {
      const val = shredditApp.getAttribute(attr);
      if (val) {
        // Could be JSON or plain username
        try {
          const parsed = JSON.parse(val);
          const name = parsed.name || parsed.username || parsed.displayName;
          if (name) return cleanUsername(name);
        } catch {
          const clean = cleanUsername(val);
          if (clean) return clean;
        }
      }
    }
  }

  // 2. The expand-user-drawer button area contains username
  const drawerBtn = document.querySelector(
    '#expand-user-drawer-button, button[aria-label*="avatar"], [data-testid="user-menu-button"]'
  );
  if (drawerBtn) {
    // Check nested text/spans
    const spans = drawerBtn.querySelectorAll('span, faceplate-screen-reader-content');
    for (const span of spans) {
      const text = span.textContent.trim();
      // Reddit shows "u/username" or just "username" in the button
      if (text.startsWith('u/') || /^[\w-]{3,20}$/.test(text)) {
        const clean = cleanUsername(text);
        if (clean) return clean;
      }
    }
    // Check aria-label on button itself
    const ariaLabel = drawerBtn.getAttribute('aria-label') || '';
    const ariaMatch = ariaLabel.match(/u\/([\w-]{3,20})/);
    if (ariaMatch) return ariaMatch[1];
  }

  // 3. Profile link in the header/user menu area
  const profileLink = document.querySelector(
    'a[href*="/user/"][data-testid="user-menu-profile-link"]'
  ) || document.querySelector(
    'faceplate-tracker[source="profile_menu"] a[href*="/user/"]'
  ) || document.querySelector(
    'a[href*="/user/"][id*="profile"]'
  );

  if (profileLink) {
    return extractUsernameFromHref(profileLink.getAttribute('href'));
  }

  // 4. Try header-area links to /user/
  const headerLinks = document.querySelectorAll(
    'header a[href*="/user/"], nav a[href*="/user/"], ' +
    '[data-testid="left-sidebar"] a[href*="/user/"], ' +
    'reddit-sidebar-nav a[href*="/user/"]'
  );
  for (const link of headerLinks) {
    const username = extractUsernameFromHref(link.getAttribute('href'));
    if (username) return username;
  }

  // 5. User drawer content (if open)
  const userDrawer = document.querySelector('#user-drawer-content');
  if (userDrawer) {
    const link = userDrawer.querySelector('a[href*="/user/"]');
    if (link) return extractUsernameFromHref(link.getAttribute('href'));
  }

  // 6. Look for reddit-header-action-items or any custom elements with user data
  const actionItems = document.querySelector('reddit-header-action-items, reddit-header-large');
  if (actionItems) {
    const link = actionItems.querySelector('a[href*="/user/"]');
    if (link) return extractUsernameFromHref(link.getAttribute('href'));
  }

  return null;
}

/**
 * Strategy for old Reddit: parse username from header user link.
 * @returns {string|null}
 */
function tryOldReddit() {
  // Primary: the user link in the top-right header
  const userLink = document.querySelector('#header-bottom-right .user a');
  if (userLink) {
    // The text is just the username on old Reddit
    const text = cleanUsername(userLink.textContent);
    if (text) return text;
    // Fallback: parse from href
    return extractUsernameFromHref(userLink.getAttribute('href'));
  }

  // Secondary: the logout form sometimes has a hidden input
  const logoutForm = document.querySelector('#logout-form, form[action*="logout"]');
  if (logoutForm) {
    const nameEl = logoutForm.querySelector('[name="user"]');
    if (nameEl?.value) return cleanUsername(nameEl.value);
  }

  return null;
}

/**
 * Strategy for redesign variant: try data-testid selectors and profile links.
 * @returns {string|null}
 */
function tryRedesign() {
  // Primary: user drawer name
  const drawerName = document.querySelector('[data-testid="user-drawer-name"]');
  if (drawerName) {
    return cleanUsername(drawerName.textContent);
  }

  // Secondary: user dropdown
  const dropdown = document.querySelector('#USER_DROPDOWN_ID span');
  if (dropdown) {
    return cleanUsername(dropdown.textContent);
  }

  // Tertiary: profile link in the user menu
  const profileLinks = document.querySelectorAll('a[href*="/user/"]');
  for (const link of profileLinks) {
    const href = link.getAttribute('href');
    // Only consider links that look like profile navigation (not post/comment author links)
    if (href && (
      link.closest('[data-testid*="user"]') ||
      link.closest('#USER_DROPDOWN') ||
      link.closest('header') ||
      link.closest('nav')
    )) {
      const username = extractUsernameFromHref(href);
      if (username) return username;
    }
  }

  return null;
}

/**
 * Fallback: look for meta tag or any reliable global indicator.
 * @returns {string|null}
 */
function tryMetaAndGlobal() {
  // Meta tag (sometimes present on profile pages or when logged in)
  const metaProfile = document.querySelector('meta[property="profile:username"]');
  if (metaProfile) {
    return cleanUsername(metaProfile.getAttribute('content'));
  }

  // Reddit sometimes exposes user data in a script tag (JSON config)
  const configScript = document.getElementById('data');
  if (configScript) {
    try {
      const data = JSON.parse(configScript.textContent);
      if (data?.user?.name) return cleanUsername(data.user.name);
    } catch { /* ignore parse errors */ }
  }

  // Last resort: scan all script tags for user config JSON
  const scripts = document.querySelectorAll('script[type="application/json"]');
  for (const script of scripts) {
    try {
      const data = JSON.parse(script.textContent);
      // Reddit config objects sometimes have user.name or session.user
      const name = data?.user?.name || data?.session?.user?.name || data?.config?.user?.name;
      if (name) return cleanUsername(name);
    } catch { /* skip non-JSON or malformed */ }
  }

  return null;
}

/**
 * Detect the currently logged-in Reddit username.
 *
 * Tries multiple strategies in order:
 * 1. Variant-aware selectors (from reddit-selectors.js)
 * 2. Variant-specific DOM parsing
 * 3. Meta tags and global fallbacks
 *
 * @returns {string|null} - Username (no "u/" prefix) or null if not detected
 */
export function getCurrentUsername() {
  // Strategy 1: Use the selector system
  const fromSelectors = trySelectors();
  if (fromSelectors) return fromSelectors;

  // Strategy 2: Variant-specific parsing
  const { detectRedditVariant } = globalThis.RAMP?.selectors || {};
  const variant = detectRedditVariant?.() || 'redesign';

  let fromVariant = null;
  switch (variant) {
    case 'shreddit':
      fromVariant = tryShreddit();
      break;
    case 'old':
      fromVariant = tryOldReddit();
      break;
    case 'redesign':
      fromVariant = tryRedesign();
      break;
  }
  if (fromVariant) return fromVariant;

  // Strategy 3: Meta tags and global config
  const fromMeta = tryMetaAndGlobal();
  if (fromMeta) return fromMeta;

  // All strategies failed — user likely not logged in or DOM structure changed
  return null;
}

/**
 * Async version that also tries Reddit's /api/me.json endpoint as a last resort.
 * This is 100% reliable when logged in (same-origin fetch with cookies).
 * @returns {Promise<string|null>}
 */
async function getCurrentUsernameAsync() {
  // First try synchronous methods
  const sync = getCurrentUsername();
  if (sync) return sync;

  // Last resort: fetch Reddit API (same-origin, session cookies apply)
  try {
    const resp = await fetch('https://www.reddit.com/api/me.json', {
      credentials: 'include',
      headers: { 'Accept': 'application/json' },
    });
    if (resp.ok) {
      const data = await resp.json();
      const name = data?.data?.name || data?.name;
      if (name) return cleanUsername(name);
    }
  } catch { /* network or CORS error — skip */ }

  return null;
}

// Expose on globalThis.RAMP namespace for inter-file access
globalThis.RAMP = globalThis.RAMP || {};
globalThis.RAMP.username = { getCurrentUsername, getCurrentUsernameAsync };
