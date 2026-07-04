/**
 * RAMP Extension — Banner Dismissal Module
 *
 * Canonical module for dismissing Reddit app promo banners, overlays,
 * bottom sheets, and xpromo elements before the debugger click sequence.
 *
 * Exports: dismissBanners()
 * Returns: { dismissed: boolean, banner_type: string | null }
 */

(function () {
  'use strict';

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  /**
   * Dismiss Reddit app promo banners and overlays.
   * Tries multiple strategies in order of specificity.
   * Should be called BEFORE the debugger click sequence in the executor flow.
   *
   * @returns {Promise<{dismissed: boolean, banner_type: string|null}>}
   */
  async function dismissBanners() {
    let dismissed = false;
    let banner_type = null;

    // ─── Strategy 1: xpromo-banner close button ─────────────────────────────
    const xpromoBannerBtn = document.querySelector(
      'xpromo-banner button, xpromo-nsfw-blocking-container button'
    );
    if (xpromoBannerBtn) {
      xpromoBannerBtn.click();
      dismissed = true;
      banner_type = 'xpromo-banner';
      console.log('[RAMP BANNER] Dismissed xpromo-banner');
      await sleep(400);
    }

    // ─── Strategy 2: aria-label close/dismiss buttons (case-insensitive) ────
    if (!dismissed) {
      const ariaButtons = document.querySelectorAll('button[aria-label]');
      const closeBtn = Array.from(ariaButtons).find(btn => {
        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
        return label.includes('close') || label.includes('dismiss');
      });
      if (closeBtn) {
        closeBtn.click();
        dismissed = true;
        banner_type = 'aria-label-close';
        console.log('[RAMP BANNER] Dismissed via aria-label button:', closeBtn.getAttribute('aria-label'));
        await sleep(400);
      }
    }

    // ─── Strategy 3: Shreddit app promo specific ────────────────────────────
    if (!dismissed) {
      const shredditPromoBtn = document.querySelector(
        'shreddit-app-promo button[aria-label="Close"], ' +
        'shreddit-app-promo button'
      );
      if (shredditPromoBtn) {
        shredditPromoBtn.click();
        dismissed = true;
        banner_type = 'shreddit-app-promo';
        console.log('[RAMP BANNER] Dismissed shreddit-app-promo');
        await sleep(400);
      }
    }

    // ─── Strategy 4: Generic overlay / modal dismiss ────────────────────────
    if (!dismissed) {
      const overlayBtn = document.querySelector(
        '[data-testid="xpromo-nsfw-modal"] button, ' +
        '[data-testid="xpromo-modal"] button, ' +
        '[data-testid="app-promo-modal"] button, ' +
        'div[class*="xpromo"] button, ' +
        'div[class*="AppPromo"] button'
      );
      if (overlayBtn) {
        overlayBtn.click();
        dismissed = true;
        banner_type = 'overlay-modal';
        console.log('[RAMP BANNER] Dismissed overlay/modal');
        await sleep(400);
      }
    }

    // ─── Strategy 5: Bottom sheet dismiss ───────────────────────────────────
    // Always try bottom sheet even if a banner was dismissed (they can coexist)
    const bottomSheetBtn = document.querySelector(
      'shreddit-bottom-sheet button[slot="close-button"], ' +
      'button[data-testid="bottom-sheet-close"], ' +
      'a[href*="continue"][data-testid]'
    );
    if (bottomSheetBtn) {
      bottomSheetBtn.click();
      if (!dismissed) {
        dismissed = true;
        banner_type = 'bottom-sheet';
      } else {
        banner_type += '+bottom-sheet';
      }
      console.log('[RAMP BANNER] Dismissed bottom sheet');
      await sleep(400);
    }

    // ─── Strategy 6: "Continue" / "Not now" / "Use web" links ───────────────
    if (!dismissed) {
      const continueLink = document.querySelector(
        'a[href*="continue"][data-testid], ' +
        'button[data-testid*="continue"], ' +
        'a[data-testid*="web"], ' +
        'button[data-testid*="dismiss"]'
      );
      if (continueLink) {
        continueLink.click();
        dismissed = true;
        banner_type = 'continue-link';
        console.log('[RAMP BANNER] Dismissed via continue/web link');
        await sleep(400);
      }
    }

    // ─── Log result ─────────────────────────────────────────────────────────
    if (dismissed) {
      console.log(`[RAMP BANNER] Banner dismissed — type: ${banner_type}`);
    } else {
      console.log('[RAMP BANNER] No banners detected');
    }

    return { dismissed, banner_type };
  }

  // Export for use in content script bundle
  globalThis.RAMP = globalThis.RAMP || {};
  globalThis.RAMP.bannerDismiss = { dismissBanners };
})();
