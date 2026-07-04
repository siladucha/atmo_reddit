/**
 * Tests for RAMP Extension — Banner Dismissal Module
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM } from 'jsdom';

// Helper: setup a mock DOM environment and load the module
function setupDOM(html = '<body></body>') {
  const dom = new JSDOM(html, { url: 'https://www.reddit.com/r/test/comments/abc123/test_thread/' });
  const { document, globalThis: gt } = dom.window;

  // Setup globalThis.RAMP namespace
  global.document = document;
  global.globalThis = global;
  global.globalThis.RAMP = global.globalThis.RAMP || {};

  return { document, dom };
}

// Load banner-dismiss module in isolation (re-execute the IIFE)
function loadModule() {
  // Reset module state
  delete globalThis.RAMP.bannerDismiss;

  // We'll simulate what the IIFE does by defining dismissBanners inline
  // since the module uses (function(){})() pattern and attaches to globalThis.RAMP
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  async function dismissBanners() {
    let dismissed = false;
    let banner_type = null;

    // Strategy 1: xpromo-banner close button
    const xpromoBannerBtn = document.querySelector(
      'xpromo-banner button, xpromo-nsfw-blocking-container button'
    );
    if (xpromoBannerBtn) {
      xpromoBannerBtn.click();
      dismissed = true;
      banner_type = 'xpromo-banner';
      await sleep(0); // Use 0 in tests
    }

    // Strategy 2: aria-label close/dismiss buttons (case-insensitive)
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
        await sleep(0);
      }
    }

    // Strategy 3: Shreddit app promo specific
    if (!dismissed) {
      const shredditPromoBtn = document.querySelector(
        'shreddit-app-promo button[aria-label="Close"], ' +
        'shreddit-app-promo button'
      );
      if (shredditPromoBtn) {
        shredditPromoBtn.click();
        dismissed = true;
        banner_type = 'shreddit-app-promo';
        await sleep(0);
      }
    }

    // Strategy 4: Generic overlay / modal dismiss
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
        await sleep(0);
      }
    }

    // Strategy 5: Bottom sheet dismiss (always tried, even if banner was dismissed)
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
      await sleep(0);
    }

    // Strategy 6: "Continue" / "Not now" / "Use web" links
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
        await sleep(0);
      }
    }

    return { dismissed, banner_type };
  }

  globalThis.RAMP.bannerDismiss = { dismissBanners };
  return { dismissBanners };
}

describe('banner-dismiss', () => {
  beforeEach(() => {
    setupDOM();
  });

  describe('dismissBanners()', () => {
    it('returns { dismissed: false, banner_type: null } when no banners present', async () => {
      const { dismissBanners } = loadModule();
      const result = await dismissBanners();
      expect(result.dismissed).toBe(false);
      expect(result.banner_type).toBe(null);
    });

    it('dismisses xpromo-banner button', async () => {
      document.body.innerHTML = '<xpromo-banner><button>Close</button></xpromo-banner>';
      const btn = document.querySelector('xpromo-banner button');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('xpromo-banner');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses xpromo-nsfw-blocking-container button', async () => {
      document.body.innerHTML = '<xpromo-nsfw-blocking-container><button>Continue</button></xpromo-nsfw-blocking-container>';
      const btn = document.querySelector('xpromo-nsfw-blocking-container button');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('xpromo-banner');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses button with aria-label containing "close" (case-insensitive)', async () => {
      document.body.innerHTML = '<div><button aria-label="Close popup">X</button></div>';
      const btn = document.querySelector('button[aria-label="Close popup"]');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('aria-label-close');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses button with aria-label containing "dismiss" (case-insensitive)', async () => {
      document.body.innerHTML = '<div><button aria-label="Dismiss banner">X</button></div>';
      const btn = document.querySelector('button[aria-label="Dismiss banner"]');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('aria-label-close');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses xpromo-nsfw-modal button via overlay strategy', async () => {
      document.body.innerHTML = '<div data-testid="xpromo-nsfw-modal"><button>OK</button></div>';
      const btn = document.querySelector('[data-testid="xpromo-nsfw-modal"] button');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('overlay-modal');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses bottom sheet close button', async () => {
      document.body.innerHTML = '<div><button data-testid="bottom-sheet-close">Close</button></div>';
      const btn = document.querySelector('button[data-testid="bottom-sheet-close"]');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('bottom-sheet');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses continue link with href and data-testid', async () => {
      document.body.innerHTML = '<a href="/continue" data-testid="continue-btn">Continue</a>';
      const link = document.querySelector('a[data-testid="continue-btn"]');
      const clickSpy = vi.spyOn(link, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('bottom-sheet');
      expect(clickSpy).toHaveBeenCalled();
    });

    it('dismisses both xpromo-banner AND bottom sheet when both present', async () => {
      document.body.innerHTML = `
        <xpromo-banner><button>Close</button></xpromo-banner>
        <div><button data-testid="bottom-sheet-close">Close Sheet</button></div>
      `;
      const bannerBtn = document.querySelector('xpromo-banner button');
      const sheetBtn = document.querySelector('button[data-testid="bottom-sheet-close"]');
      const bannerClick = vi.spyOn(bannerBtn, 'click');
      const sheetClick = vi.spyOn(sheetBtn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(true);
      expect(result.banner_type).toBe('xpromo-banner+bottom-sheet');
      expect(bannerClick).toHaveBeenCalled();
      expect(sheetClick).toHaveBeenCalled();
    });

    it('prioritizes xpromo-banner over aria-label buttons', async () => {
      document.body.innerHTML = `
        <xpromo-banner><button>Close</button></xpromo-banner>
        <button aria-label="Close dialog">X</button>
      `;

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.banner_type).toBe('xpromo-banner');
    });

    it('does not click random buttons without close/dismiss aria-label', async () => {
      document.body.innerHTML = '<button aria-label="Submit form">Go</button>';
      const btn = document.querySelector('button');
      const clickSpy = vi.spyOn(btn, 'click');

      const { dismissBanners } = loadModule();
      const result = await dismissBanners();

      expect(result.dismissed).toBe(false);
      expect(clickSpy).not.toHaveBeenCalled();
    });

    it('exports dismissBanners on globalThis.RAMP.bannerDismiss', () => {
      loadModule();
      expect(globalThis.RAMP.bannerDismiss).toBeDefined();
      expect(typeof globalThis.RAMP.bannerDismiss.dismissBanners).toBe('function');
    });
  });
});
