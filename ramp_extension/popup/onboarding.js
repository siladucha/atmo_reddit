/**
 * RAMP Extension — Zero-input Onboarding
 *
 * Flow:
 * 1. Detect Reddit username from open tabs (content script)
 * 2. If no Reddit → show "log in" instructions
 * 3. If Reddit found → auto-POST /api/extension/activate { username }
 * 4. Backend validates avatar exists → returns JWT + nodeId
 * 5. Save auth → show "Connected!" → redirect to popup
 *
 * Zero manual input. Just have Reddit open + extension installed.
 */

import { saveAuth } from '../shared/auth.js';

const RAMP_URL = 'https://gorampit.com';

// Steps
const stepDetect = document.getElementById('step-detect');
const stepNoReddit = document.getElementById('step-no-reddit');
const stepConnecting = document.getElementById('step-connecting');
const stepNotFound = document.getElementById('step-not-found');
const stepSuccess = document.getElementById('step-success');

function showStep(el) {
  [stepDetect, stepNoReddit, stepConnecting, stepNotFound, stepSuccess]
    .forEach(s => s.classList.add('hidden'));
  el.classList.remove('hidden');
}

// ─── Detect Reddit Username ────────────────────────────────────────────────

async function detectUsername() {
  showStep(stepDetect);

  // Short delay to let content scripts initialize
  await sleep(500);

  const tabs = await chrome.tabs.query({
    url: ['https://www.reddit.com/*', 'https://old.reddit.com/*'],
  });

  if (tabs.length === 0) {
    showStep(stepNoReddit);
    return;
  }

  for (const tab of tabs) {
    try {
      const resp = await chrome.tabs.sendMessage(tab.id, { type: 'GET_USERNAME' });
      if (resp && resp.username) {
        await activateWithUsername(resp.username);
        return;
      }
    } catch {
      continue;
    }
  }

  // Reddit tabs open but not logged in
  showStep(stepNoReddit);
}

// ─── Activate with Backend ─────────────────────────────────────────────────

async function activateWithUsername(username) {
  document.getElementById('connecting-username').textContent = `u/${username}`;
  showStep(stepConnecting);

  try {
    const resp = await fetch(`${RAMP_URL}/api/extension/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reddit_username: username,
        extension_version: chrome.runtime.getManifest().version,
      }),
    });

    if (resp.status === 404) {
      document.getElementById('notfound-username').textContent = `u/${username}`;
      showStep(stepNotFound);
      return;
    }

    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      document.getElementById('notfound-username').textContent = body.detail || `Error ${resp.status}`;
      showStep(stepNotFound);
      return;
    }

    const data = await resp.json();

    await saveAuth({
      token: data.token,
      nodeId: data.execution_node_id,
      rampUrl: RAMP_URL,
      avatarUsername: username,
    });

    // Tell service worker about the active username
    chrome.runtime.sendMessage({ type: 'SET_ACTIVE_USERNAME', username });

    document.getElementById('success-username').textContent = `u/${username}`;
    showStep(stepSuccess);
  } catch (err) {
    document.getElementById('notfound-username').textContent = err.message || 'Network error';
    showStep(stepNotFound);
  }
}

// ─── Events ────────────────────────────────────────────────────────────────

document.getElementById('retry-btn').addEventListener('click', detectUsername);
document.getElementById('retry-btn-2').addEventListener('click', detectUsername);
document.getElementById('done-btn').addEventListener('click', () => {
  window.location.href = 'popup.html';
});

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─── Init ──────────────────────────────────────────────────────────────────
detectUsername();
