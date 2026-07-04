/**
 * RAMP Extension — HMAC Verifier
 *
 * Validates task_hash (HMAC-SHA256) on incoming tasks before they enter
 * the local queue. Ensures tasks were signed by the RAMP backend and
 * have not been tampered with in transit.
 *
 * Uses Web Crypto API (crypto.subtle) — available in MV3 service workers.
 *
 * HMAC message format (must match backend extension_dispatcher.py):
 *   "{idempotency_key}:{task_type}:{avatar_username}:{target}"
 *   where target = thread_url (post_comment) or probe_type (diagnostic_probe)
 *
 * Exports:
 *   verifyTaskHmac(task, secret) — verify task integrity
 *   computeHmacSha256(secret, message) — compute HMAC-SHA256 hex digest
 *   arrayBufferToHex(buffer) — convert ArrayBuffer to hex string
 */

/**
 * Convert an ArrayBuffer to a lowercase hex string.
 * @param {ArrayBuffer} buffer
 * @returns {string} Hex-encoded string
 */
export function arrayBufferToHex(buffer) {
  const bytes = new Uint8Array(buffer);
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0');
  }
  return hex;
}

/**
 * Compute HMAC-SHA256 of a message using Web Crypto API.
 * Returns the hex-encoded digest (matches Python hmac.new(...).hexdigest()).
 *
 * @param {string} secret — HMAC secret key
 * @param {string} message — message to sign
 * @returns {Promise<string>} Hex-encoded HMAC-SHA256 digest
 */
export async function computeHmacSha256(secret, message) {
  const encoder = new TextEncoder();

  // Import the secret as a CryptoKey for HMAC-SHA256
  const keyData = encoder.encode(secret);
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    keyData,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  // Sign the message
  const messageData = encoder.encode(message);
  const signature = await crypto.subtle.sign('HMAC', cryptoKey, messageData);

  return arrayBufferToHex(signature);
}

/**
 * Verify the HMAC signature on a task object.
 *
 * Computes the expected HMAC-SHA256 hash from the task fields and compares
 * it to the task_hash provided by the backend. This ensures the task was
 * created by the RAMP backend and has not been modified.
 *
 * @param {object} task — Task object from GET /api/extension/tasks
 * @param {string} task.idempotency_key — unique delivery key
 * @param {string} task.task_type — "post_comment" or "diagnostic_probe"
 * @param {string} task.avatar_username — Reddit username of the avatar
 * @param {string} [task.thread_url] — target URL (for post_comment)
 * @param {string} [task.probe_type] — probe type (for diagnostic_probe)
 * @param {string} task.task_hash — HMAC-SHA256 hex digest from backend
 * @param {string} secret — HMAC secret (stored locally from registration/config)
 * @returns {Promise<{valid: boolean, error?: string}>}
 */
export async function verifyTaskHmac(task, secret) {
  // Validate inputs
  if (!task || typeof task !== 'object') {
    return { valid: false, error: 'task is not a valid object' };
  }

  if (!secret || typeof secret !== 'string') {
    return { valid: false, error: 'secret is missing or not a string' };
  }

  if (!task.task_hash || typeof task.task_hash !== 'string') {
    return { valid: false, error: 'task_hash is missing or not a string' };
  }

  if (!task.idempotency_key) {
    return { valid: false, error: 'idempotency_key is missing' };
  }

  if (!task.task_type) {
    return { valid: false, error: 'task_type is missing' };
  }

  if (!task.avatar_username) {
    return { valid: false, error: 'avatar_username is missing' };
  }

  // Determine target based on task_type
  let target;
  if (task.task_type === 'post_comment') {
    target = task.thread_url || '';
  } else if (task.task_type === 'diagnostic_probe') {
    target = task.probe_type || '';
  } else {
    return { valid: false, error: `unknown task_type: ${task.task_type}` };
  }

  // Build message in same format as backend:
  // "{idempotency_key}:{task_type}:{avatar_username}:{target}"
  const message = `${task.idempotency_key}:${task.task_type}:${task.avatar_username}:${target}`;

  // Compute expected HMAC
  const expectedHash = await computeHmacSha256(secret, message);

  // Constant-time comparison (prevents timing attacks)
  if (expectedHash.length !== task.task_hash.length) {
    return { valid: false, error: 'task_hash length mismatch' };
  }

  let mismatch = 0;
  for (let i = 0; i < expectedHash.length; i++) {
    mismatch |= expectedHash.charCodeAt(i) ^ task.task_hash.charCodeAt(i);
  }

  if (mismatch !== 0) {
    return { valid: false, error: 'HMAC verification failed — signature mismatch' };
  }

  return { valid: true };
}
