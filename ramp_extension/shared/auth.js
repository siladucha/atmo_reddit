/**
 * RAMP Extension — Auth Module
 *
 * Handles JWT token storage/retrieval for backend communication.
 * All data persisted in chrome.storage.local (survives service worker restarts).
 *
 * Stored shape:
 *   { ramp_auth: { token, nodeId, rampUrl } }
 */

const STORAGE_KEY = 'ramp_auth';

/**
 * Save authentication data received during registration.
 * @param {{ token: string, nodeId: string, rampUrl: string, avatarUsername?: string }} data
 */
export async function saveAuth(data) {
  const { token, nodeId, rampUrl, avatarUsername } = data;
  await chrome.storage.local.set({
    [STORAGE_KEY]: { token, nodeId, rampUrl, avatarUsername },
  });
}

/**
 * Retrieve stored auth data.
 * @returns {Promise<{ token: string, nodeId: string, rampUrl: string } | null>}
 */
export async function getAuth() {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  return result[STORAGE_KEY] || null;
}

/**
 * Remove all auth data (logout / reset).
 */
export async function clearAuth() {
  await chrome.storage.local.remove(STORAGE_KEY);
}

/**
 * Check whether the extension has a stored token.
 * @returns {Promise<boolean>}
 */
export async function isAuthenticated() {
  const auth = await getAuth();
  return auth !== null && typeof auth.token === 'string' && auth.token.length > 0;
}

/**
 * Build Authorization headers for backend API calls.
 * @returns {Promise<{ Authorization: string } | null>} Headers object, or null if not authenticated.
 */
export async function getHeaders() {
  const auth = await getAuth();
  if (!auth || !auth.token) {
    return null;
  }
  return { Authorization: `Bearer ${auth.token}` };
}
