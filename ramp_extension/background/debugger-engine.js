/**
 * Debugger Engine — Trusted Click via chrome.debugger API
 *
 * Uses Chrome DevTools Protocol (CDP) to dispatch browser-native mouse events
 * that pass Reddit's `isTrusted` checks on Shadow DOM web components.
 *
 * Flow per click:
 *   1. Get element coordinates via content script message (GET_ELEMENT_COORDS)
 *   2. Attach debugger to tab (CDP version 1.3)
 *   3. Dispatch mousePressed at element center
 *   4. Dispatch mouseReleased at element center
 *   5. Detach debugger
 *
 * Error handling:
 *   - Element not found → throws 'Element not found for click'
 *   - Element not visible (0 width/height) → throws 'Element not visible for click'
 *   - Debugger attach failed → throws with original error, ensures cleanup
 *   - Any error during dispatch → detaches debugger before re-throwing
 *
 * Shadow DOM support:
 *   - Pass `shadowSelector` to reach elements inside a shadow root
 *   - Content script resolves: host.shadowRoot.querySelector(shadowSelector)
 *
 * Message format sent to content script:
 *   {
 *     type: 'GET_ELEMENT_COORDS',
 *     selector: string,        // CSS selector for the host element
 *     shadowSelector: string|null  // Optional selector inside shadow root
 *   }
 *
 * Expected response from content script:
 *   { x: number, y: number, width: number, height: number } | null
 */

const CDP_VERSION = '1.3';

/**
 * Perform a trusted click on an element identified by CSS selector.
 *
 * @param {number} tabId - Chrome tab ID where the element exists
 * @param {string} selector - CSS selector for the target element (or shadow host)
 * @param {string|null} shadowSelector - Optional selector inside the element's shadow root
 * @throws {Error} If element not found, not visible, or debugger operations fail
 */
export async function trustedClick(tabId, selector, shadowSelector = null) {
  // 1. Get element coordinates via content script
  const coords = await chrome.tabs.sendMessage(tabId, {
    type: 'GET_ELEMENT_COORDS',
    selector,
    shadowSelector,
  });

  if (!coords) {
    throw new Error('Element not found for click');
  }

  // Validate element is visible (non-zero dimensions)
  if (coords.width === 0 || coords.height === 0) {
    throw new Error('Element not visible for click');
  }

  // 2. Calculate center point of the element
  const x = coords.x + coords.width / 2;
  const y = coords.y + coords.height / 2;

  // 3. Attach debugger, dispatch events, detach — with cleanup on error
  let attached = false;

  try {
    await chrome.debugger.attach({ tabId }, CDP_VERSION);
    attached = true;

    // 4. Dispatch mousePressed
    await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
      type: 'mousePressed',
      x,
      y,
      button: 'left',
      clickCount: 1,
    });

    // 5. Dispatch mouseReleased
    await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x,
      y,
      button: 'left',
      clickCount: 1,
    });

    // 6. Detach debugger
    await chrome.debugger.detach({ tabId });
    attached = false;
  } catch (err) {
    // Ensure debugger is detached on any error
    if (attached) {
      try {
        await chrome.debugger.detach({ tabId });
      } catch (detachErr) {
        // Swallow detach errors during cleanup — original error is more important
        console.warn('[RAMP Debugger] Cleanup detach failed:', detachErr.message);
      }
    }
    throw err;
  }
}
