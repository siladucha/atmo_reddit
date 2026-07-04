import { describe, it, expect, beforeEach } from 'vitest';
import { getCurrentUsername } from './reddit-username.js';
// Import selectors to ensure globalThis.RAMP.selectors is available
import './reddit-selectors.js';

describe('getCurrentUsername', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  describe('shreddit variant', () => {
    it('detects username from faceplate-tracker span', () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <faceplate-tracker source="profile_menu">
          <span>TestUser123</span>
        </faceplate-tracker>
      `;
      expect(getCurrentUsername()).toBe('TestUser123');
    });

    it('detects username from profile link href', () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <a href="/user/Flaky_Finder_13" data-testid="user-menu-profile-link">Profile</a>
      `;
      expect(getCurrentUsername()).toBe('Flaky_Finder_13');
    });

    it('detects username from faceplate-tracker profile link', () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <faceplate-tracker source="profile_menu">
          <a href="/user/Hot-Thought2408">My Profile</a>
        </faceplate-tracker>
      `;
      expect(getCurrentUsername()).toBe('Hot-Thought2408');
    });
  });

  describe('old Reddit variant', () => {
    it('detects username from header user link text', () => {
      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div id="header-bottom-right">
          <span class="user">
            <a href="https://old.reddit.com/user/StopAutomatic717">StopAutomatic717</a>
          </span>
        </div>
      `;
      expect(getCurrentUsername()).toBe('StopAutomatic717');
    });

    it('detects username from user link href when text is weird', () => {
      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div id="header-bottom-right">
          <span class="user">
            <a href="/user/cool_user_99">cool_user_99 (42)</a>
          </span>
        </div>
      `;
      // text "cool_user_99 (42)" won't match the username regex, so falls to href
      expect(getCurrentUsername()).toBe('cool_user_99');
    });
  });

  describe('redesign variant', () => {
    it('detects username from user-drawer-name', () => {
      document.body.innerHTML = `
        <div data-testid="user-drawer-name">connor_lloyd</div>
      `;
      expect(getCurrentUsername()).toBe('connor_lloyd');
    });

    it('detects username from USER_DROPDOWN_ID span', () => {
      document.body.innerHTML = `
        <div id="USER_DROPDOWN_ID">
          <span>naomi_rush</span>
        </div>
      `;
      expect(getCurrentUsername()).toBe('naomi_rush');
    });

    it('detects username from profile link in header', () => {
      document.body.innerHTML = `
        <header>
          <a href="/user/leon_grant10">Profile</a>
        </header>
      `;
      expect(getCurrentUsername()).toBe('leon_grant10');
    });
  });

  describe('meta tag fallback', () => {
    it('detects username from meta property tag', () => {
      document.body.innerHTML = `
        <head>
          <meta property="profile:username" content="meta_user_01">
        </head>
      `;
      // Move meta into head for jsdom
      const meta = document.createElement('meta');
      meta.setAttribute('property', 'profile:username');
      meta.setAttribute('content', 'meta_user_01');
      document.head.appendChild(meta);
      document.body.innerHTML = '<div>some page</div>';
      expect(getCurrentUsername()).toBe('meta_user_01');
      document.head.innerHTML = '';
    });
  });

  describe('edge cases', () => {
    it('returns null when not logged in (empty page)', () => {
      document.body.innerHTML = '<div>No user elements</div>';
      expect(getCurrentUsername()).toBeNull();
    });

    it('strips u/ prefix from username text', () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <faceplate-tracker source="profile_menu">
          <span>u/PrefixedUser</span>
        </faceplate-tracker>
      `;
      expect(getCurrentUsername()).toBe('PrefixedUser');
    });

    it('strips /u/ prefix from username text', () => {
      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div id="header-bottom-right">
          <span class="user">
            <a href="/user/slash_user">/u/slash_user</a>
          </span>
        </div>
      `;
      expect(getCurrentUsername()).toBe('slash_user');
    });

    it('returns null for invalid username (too short)', () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <faceplate-tracker source="profile_menu">
          <span>ab</span>
        </faceplate-tracker>
      `;
      // 'ab' is too short (< 3 chars), so selector result is null
      // Falls through to variant-specific, then meta — all null
      expect(getCurrentUsername()).toBeNull();
    });

    it('handles username with hyphens and underscores', () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <faceplate-tracker source="profile_menu">
          <span>Cool-User_123</span>
        </faceplate-tracker>
      `;
      expect(getCurrentUsername()).toBe('Cool-User_123');
    });
  });

  describe('globalThis.RAMP.username namespace', () => {
    it('exposes getCurrentUsername on globalThis.RAMP.username', () => {
      expect(globalThis.RAMP.username).toBeDefined();
      expect(globalThis.RAMP.username.getCurrentUsername).toBe(getCurrentUsername);
    });
  });
});
