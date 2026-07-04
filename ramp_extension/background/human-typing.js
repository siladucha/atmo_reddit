/**
 * Human Typing Simulation — CDP Keystroke Engine
 *
 * NOT ACTIVE. This module is prepared for activation when A/B test results
 * indicate that bulk textarea.value insertion is being detected by Reddit.
 *
 * Uses chrome.debugger CDP `Input.dispatchKeyEvent` to send individual
 * keystrokes with realistic timing, occasional typos, and corrections.
 *
 * Activation trigger: A/B test (`extension-posting-ab-test` spec) shows
 * `old_reddit` group shadowban rate > `manual_email` group by ≥2σ.
 *
 * Integration point: Replace the `OLD_REDDIT_INSERT_TEXT` bulk assignment
 * in executor-old-reddit.js with a call to `humanType(tabId, text)`.
 *
 * @module background/human-typing
 * @status DORMANT — do not import until A/B test signals need
 */

// ─── QWERTY Adjacency Map (for realistic typos) ─────────────────────────────

const ADJACENT_KEYS = {
  q: ['w', 'a'], w: ['q', 'e', 'a', 's'],
  e: ['w', 'r', 's', 'd'], r: ['e', 't', 'd', 'f'],
  t: ['r', 'y', 'f', 'g'], y: ['t', 'u', 'g', 'h'],
  u: ['y', 'i', 'h', 'j'], i: ['u', 'o', 'j', 'k'],
  o: ['i', 'p', 'k', 'l'], p: ['o', 'l'],
  a: ['q', 'w', 's', 'z'], s: ['a', 'd', 'w', 'e', 'z', 'x'],
  d: ['s', 'f', 'e', 'r', 'x', 'c'], f: ['d', 'g', 'r', 't', 'c', 'v'],
  g: ['f', 'h', 't', 'y', 'v', 'b'], h: ['g', 'j', 'y', 'u', 'b', 'n'],
  j: ['h', 'k', 'u', 'i', 'n', 'm'], k: ['j', 'l', 'i', 'o', 'm'],
  l: ['k', 'o', 'p'], z: ['a', 'x'], x: ['z', 'c', 's', 'd'],
  c: ['x', 'v', 'd', 'f'], v: ['c', 'b', 'f', 'g'],
  b: ['v', 'n', 'g', 'h'], n: ['b', 'm', 'h', 'j'],
  m: ['n', 'j', 'k'],
};

// ─── Configuration ───────────────────────────────────────────────────────────

const CONFIG = {
  // Keystroke timing
  minDelay: 55,          // ms — fastest typist burst
  maxDelay: 180,         // ms — normal typing speed
  thinkingPauseChance: 0.04, // 4% chance of 500-2500ms pause (mid-thought)
  thinkingPauseMin: 500,
  thinkingPauseMax: 2500,

  // Typo simulation
  typoRate: 0.012,       // 1.2% per alphabetic character
  immediateFixRatio: 0.5, // 50% fix immediately, 50% fix after few chars

  // Delayed fix params
  delayedFixMinChars: 3,  // continue 3-12 chars before fixing
  delayedFixMaxChars: 12,
  fixPauseMin: 200,       // pause before starting correction
  fixPauseMax: 600,
};

// ─── Utilities ───────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

function randomInt(min, max) {
  return Math.floor(randomBetween(min, max + 1));
}

function getAdjacentKey(char) {
  const lower = char.toLowerCase();
  const neighbors = ADJACENT_KEYS[lower];
  if (!neighbors || neighbors.length === 0) return char;
  const picked = neighbors[Math.floor(Math.random() * neighbors.length)];
  // Preserve original case
  return char === char.toUpperCase() ? picked.toUpperCase() : picked;
}

function isAlphabetic(char) {
  return /^[a-zA-Z]$/.test(char);
}

// ─── CDP Keystroke Dispatch ──────────────────────────────────────────────────

/**
 * Send a single key press via CDP Input.dispatchKeyEvent.
 * This produces isTrusted:true keyboard events.
 */
async function dispatchKey(tabId, char) {
  const keyCode = char.charCodeAt(0);

  // keyDown
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', {
    type: 'keyDown',
    text: char,
    key: char,
    code: `Key${char.toUpperCase()}`,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });

  // char (text input event)
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', {
    type: 'char',
    text: char,
    key: char,
    code: `Key${char.toUpperCase()}`,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });

  // keyUp
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', {
    type: 'keyUp',
    key: char,
    code: `Key${char.toUpperCase()}`,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
}

/**
 * Send a special key (Backspace, ArrowLeft, ArrowRight).
 */
async function dispatchSpecialKey(tabId, key, code, keyCode) {
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', {
    type: 'keyDown',
    key,
    code,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', {
    type: 'keyUp',
    key,
    code,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
}

async function dispatchBackspace(tabId) {
  await dispatchSpecialKey(tabId, 'Backspace', 'Backspace', 8);
}

async function dispatchArrowLeft(tabId) {
  await dispatchSpecialKey(tabId, 'ArrowLeft', 'ArrowLeft', 37);
}

async function dispatchArrowRight(tabId) {
  await dispatchSpecialKey(tabId, 'ArrowRight', 'ArrowRight', 39);
}

// ─── Typing Engine ───────────────────────────────────────────────────────────

/**
 * Get a realistic inter-keystroke delay.
 * Varies based on character (spaces slightly faster, after punctuation slower).
 */
function getKeystrokeDelay(char, prevChar) {
  let base = randomBetween(CONFIG.minDelay, CONFIG.maxDelay);

  // After punctuation: slightly longer pause (sentence boundary)
  if (prevChar && /[.!?]/.test(prevChar)) {
    base += randomBetween(100, 300);
  }

  // Spaces are slightly faster (thumb key)
  if (char === ' ') {
    base *= 0.7;
  }

  // Occasional thinking pause
  if (Math.random() < CONFIG.thinkingPauseChance) {
    base += randomBetween(CONFIG.thinkingPauseMin, CONFIG.thinkingPauseMax);
  }

  return Math.round(base);
}

/**
 * Type text with human-like timing and occasional typos.
 *
 * REQUIRES: chrome.debugger already attached to tabId.
 * REQUIRES: textarea/contenteditable already focused.
 *
 * @param {number} tabId - Chrome tab ID
 * @param {string} text - Full text to type
 * @returns {Promise<{typed: number, typos: number, fixes: number}>}
 */
export async function humanType(tabId, text) {
  const chars = [...text]; // Handle Unicode properly
  let stats = { typed: 0, typos: 0, fixes: 0 };
  let prevChar = '';

  // Queue for delayed fixes: { position, correctChar }
  let delayedFixes = [];
  let charsTypedSinceLastFix = 0;

  for (let i = 0; i < chars.length; i++) {
    const char = chars[i];

    // ── Check if we need to execute a delayed fix ──
    if (delayedFixes.length > 0) {
      charsTypedSinceLastFix++;
      const fix = delayedFixes[0];
      if (charsTypedSinceLastFix >= fix.fixAfter) {
        // Execute delayed fix
        await sleep(randomBetween(CONFIG.fixPauseMin, CONFIG.fixPauseMax));

        // Arrow left N times to get to typo position
        const arrowCount = charsTypedSinceLastFix;
        for (let a = 0; a < arrowCount; a++) {
          await dispatchArrowLeft(tabId);
          await sleep(randomBetween(30, 60));
        }

        // Delete the wrong char
        await dispatchBackspace(tabId);
        await sleep(randomBetween(80, 150));

        // Type correct char
        await dispatchKey(tabId, fix.correctChar);
        await sleep(randomBetween(50, 100));

        // Arrow right to return to end
        for (let a = 0; a < arrowCount - 1; a++) {
          await dispatchArrowRight(tabId);
          await sleep(randomBetween(30, 60));
        }

        delayedFixes.shift();
        charsTypedSinceLastFix = 0;
        stats.fixes++;
      }
    }

    // ── Decide if this keystroke should be a typo ──
    const shouldTypo = isAlphabetic(char) && Math.random() < CONFIG.typoRate;

    if (shouldTypo) {
      stats.typos++;
      const wrongChar = getAdjacentKey(char);

      if (Math.random() < CONFIG.immediateFixRatio) {
        // ── Immediate fix: type wrong → pause → backspace → correct ──
        await dispatchKey(tabId, wrongChar);
        await sleep(randomBetween(200, 500)); // "notice" the mistake
        await dispatchBackspace(tabId);
        await sleep(randomBetween(80, 150));
        await dispatchKey(tabId, char); // correct character
        stats.fixes++;
      } else {
        // ── Delayed fix: type wrong, continue, fix later ──
        await dispatchKey(tabId, wrongChar);
        delayedFixes.push({
          correctChar: char,
          fixAfter: randomInt(CONFIG.delayedFixMinChars, CONFIG.delayedFixMaxChars),
        });
        charsTypedSinceLastFix = 0;
      }
    } else {
      // ── Normal keystroke ──
      await dispatchKey(tabId, char);
    }

    // Inter-keystroke delay
    const delay = getKeystrokeDelay(char, prevChar);
    await sleep(delay);

    prevChar = char;
    stats.typed++;
  }

  // ── Handle any remaining delayed fixes at end of text ──
  for (const fix of delayedFixes) {
    await sleep(randomBetween(CONFIG.fixPauseMin, CONFIG.fixPauseMax));
    const arrowCount = charsTypedSinceLastFix;
    for (let a = 0; a < arrowCount; a++) {
      await dispatchArrowLeft(tabId);
      await sleep(randomBetween(30, 60));
    }
    await dispatchBackspace(tabId);
    await sleep(randomBetween(80, 150));
    await dispatchKey(tabId, fix.correctChar);
    await sleep(randomBetween(50, 100));
    for (let a = 0; a < arrowCount - 1; a++) {
      await dispatchArrowRight(tabId);
      await sleep(randomBetween(30, 60));
    }
    stats.fixes++;
    charsTypedSinceLastFix = 0;
  }

  return stats;
}

// ─── Ghost Mouse Movement (Bézier Curves via CDP) ────────────────────────────

/**
 * Generate cubic Bézier curve points between two coordinates.
 * Models real hand movement: curved path, not straight line.
 *
 * @param {{x: number, y: number}} start
 * @param {{x: number, y: number}} end
 * @param {number} steps - Number of intermediate points
 * @returns {{x: number, y: number}[]}
 */
function bezierPath(start, end, steps = 20) {
  // Two control points with random offset from straight line
  const dx = end.x - start.x;
  const dy = end.y - start.y;

  const cx1 = start.x + dx * 0.25 + (Math.random() - 0.5) * 60;
  const cy1 = start.y + dy * 0.1 + (Math.random() - 0.5) * 60;
  const cx2 = start.x + dx * 0.75 + (Math.random() - 0.5) * 60;
  const cy2 = start.y + dy * 0.9 + (Math.random() - 0.5) * 60;

  const points = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const u = 1 - t;
    const x = u * u * u * start.x + 3 * u * u * t * cx1 + 3 * u * t * t * cx2 + t * t * t * end.x;
    const y = u * u * u * start.y + 3 * u * u * t * cy1 + 3 * u * t * t * cy2 + t * t * t * end.y;
    points.push({ x: Math.round(x), y: Math.round(y) });
  }
  return points;
}

/**
 * Move mouse along Bézier path using CDP Input.dispatchMouseEvent.
 *
 * REQUIRES: chrome.debugger already attached to tabId.
 *
 * @param {number} tabId
 * @param {{x: number, y: number}} from - Starting position
 * @param {{x: number, y: number}} to - Target position
 */
export async function ghostMove(tabId, from, to) {
  const points = bezierPath(from, to);

  for (let i = 0; i < points.length; i++) {
    await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
      type: 'mouseMoved',
      x: points[i].x,
      y: points[i].y,
    });

    // Variable delay: slower at start and end, faster in middle
    const progress = i / points.length;
    const speedFactor = Math.sin(progress * Math.PI) * 0.6 + 0.4; // 0.4-1.0
    const baseDelay = randomBetween(6, 16);
    await sleep(baseDelay / speedFactor);
  }
}

/**
 * Full ghost-cursor click: move to element center → hover pause → click.
 *
 * REQUIRES: chrome.debugger already attached to tabId.
 *
 * @param {number} tabId
 * @param {{x: number, y: number}} from - Current mouse position
 * @param {{x: number, y: number}} target - Element center
 */
export async function ghostClick(tabId, from, target) {
  // Add slight randomness to target (don't always hit dead center)
  const jitteredTarget = {
    x: target.x + (Math.random() - 0.5) * 6,
    y: target.y + (Math.random() - 0.5) * 6,
  };

  // Move along curve
  await ghostMove(tabId, from, jitteredTarget);

  // Hover pause (150-500ms — reading before clicking)
  await sleep(randomBetween(150, 500));

  // Mouse down
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: jitteredTarget.x,
    y: jitteredTarget.y,
    button: 'left',
    clickCount: 1,
  });

  // Press duration (50-130ms — human finger)
  await sleep(randomBetween(50, 130));

  // Mouse up
  await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x: jitteredTarget.x,
    y: jitteredTarget.y,
    button: 'left',
    clickCount: 1,
  });
}
