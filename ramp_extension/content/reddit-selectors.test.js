import { describe, it, expect, beforeEach } from 'vitest';
import {
  detectRedditVariant,
  SELECTORS,
  querySelector,
  querySelectorAll,
} from './reddit-selectors.js';

describe('detectRedditVariant', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('returns "shreddit" when shreddit-app element exists', () => {
    document.body.innerHTML = '<shreddit-app></shreddit-app>';
    expect(detectRedditVariant()).toBe('shreddit');
  });

  it('returns "old" when #header-bottom-left exists', () => {
    document.body.innerHTML = '<div id="header-bottom-left"></div>';
    expect(detectRedditVariant()).toBe('old');
  });

  it('returns "redesign" as default fallback', () => {
    document.body.innerHTML = '<div id="app"></div>';
    expect(detectRedditVariant()).toBe('redesign');
  });

  it('prefers shreddit over old when both exist', () => {
    document.body.innerHTML = '<shreddit-app></shreddit-app><div id="header-bottom-left"></div>';
    expect(detectRedditVariant()).toBe('shreddit');
  });
});

describe('SELECTORS', () => {
  it('has all three variants', () => {
    expect(Object.keys(SELECTORS)).toEqual(['shreddit', 'old', 'redesign']);
  });

  it('each variant has all required selector keys', () => {
    const requiredKeys = ['replyButton', 'textArea', 'submitButton', 'username', 'commentText', 'karmaDisplay'];
    for (const variant of Object.keys(SELECTORS)) {
      for (const key of requiredKeys) {
        expect(SELECTORS[variant][key], `${variant}.${key} missing`).toBeDefined();
        expect(Array.isArray(SELECTORS[variant][key]), `${variant}.${key} not array`).toBe(true);
        expect(SELECTORS[variant][key].length, `${variant}.${key} empty`).toBeGreaterThan(0);
      }
    }
  });
});

describe('querySelector', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('returns first matching element from shreddit fallback chain', () => {
    document.body.innerHTML = `
      <shreddit-app></shreddit-app>
      <button slot="reply-button">Reply</button>
    `;
    const el = querySelector('replyButton');
    expect(el).not.toBeNull();
    expect(el.textContent).toBe('Reply');
  });

  it('falls back to second selector when first fails (shreddit)', () => {
    document.body.innerHTML = `
      <shreddit-app></shreddit-app>
      <button data-testid="reply">Reply Fallback</button>
    `;
    const el = querySelector('replyButton');
    expect(el).not.toBeNull();
    expect(el.textContent).toBe('Reply Fallback');
  });

  it('returns null when all selectors in chain fail', () => {
    document.body.innerHTML = '<shreddit-app></shreddit-app><div>nothing</div>';
    const el = querySelector('replyButton');
    expect(el).toBeNull();
  });

  it('returns null for unknown selector key', () => {
    document.body.innerHTML = '<shreddit-app></shreddit-app>';
    const el = querySelector('nonExistentKey');
    expect(el).toBeNull();
  });

  it('works with old reddit variant', () => {
    document.body.innerHTML = `
      <div id="header-bottom-left"></div>
      <a class="reply-button">Reply</a>
    `;
    const el = querySelector('replyButton');
    expect(el).not.toBeNull();
    expect(el.textContent).toBe('Reply');
  });

  it('works with redesign variant', () => {
    document.body.innerHTML = `
      <div id="app"></div>
      <button data-testid="comment-reply-button">Reply</button>
    `;
    const el = querySelector('replyButton');
    expect(el).not.toBeNull();
    expect(el.textContent).toBe('Reply');
  });

  it('supports custom root element', () => {
    document.body.innerHTML = `
      <shreddit-app></shreddit-app>
      <div id="container">
        <button slot="reply-button">In Container</button>
      </div>
      <button slot="reply-button">Outside</button>
    `;
    const container = document.getElementById('container');
    const el = querySelector('replyButton', container);
    expect(el).not.toBeNull();
    expect(el.textContent).toBe('In Container');
  });
});

describe('querySelectorAll', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('returns all matching elements from first successful selector', () => {
    document.body.innerHTML = `
      <shreddit-app></shreddit-app>
      <shreddit-comment><p>Comment 1</p></shreddit-comment>
      <shreddit-comment><p>Comment 2</p></shreddit-comment>
      <shreddit-comment><p>Comment 3</p></shreddit-comment>
    `;
    const elements = querySelectorAll('commentText');
    expect(elements).toHaveLength(3);
    expect(elements[0].textContent).toBe('Comment 1');
  });

  it('falls back to second selector when first returns nothing', () => {
    document.body.innerHTML = `
      <shreddit-app></shreddit-app>
      <div slot="comment"><p>Fallback 1</p></div>
      <div slot="comment"><p>Fallback 2</p></div>
    `;
    const elements = querySelectorAll('commentText');
    expect(elements).toHaveLength(2);
    expect(elements[0].textContent).toBe('Fallback 1');
  });

  it('returns empty array when all selectors fail', () => {
    document.body.innerHTML = '<shreddit-app></shreddit-app><div>nothing</div>';
    const elements = querySelectorAll('commentText');
    expect(elements).toEqual([]);
  });

  it('returns empty array for unknown selector key', () => {
    document.body.innerHTML = '<shreddit-app></shreddit-app>';
    const elements = querySelectorAll('nonExistentKey');
    expect(elements).toEqual([]);
  });

  it('returns a plain array (not NodeList)', () => {
    document.body.innerHTML = `
      <div id="header-bottom-left"></div>
      <div class="usertext-body"><p>Text</p></div>
    `;
    const elements = querySelectorAll('commentText');
    expect(Array.isArray(elements)).toBe(true);
  });

  it('supports custom root element', () => {
    document.body.innerHTML = `
      <shreddit-app></shreddit-app>
      <div id="thread">
        <shreddit-comment><p>Thread Comment</p></shreddit-comment>
      </div>
      <shreddit-comment><p>Outside</p></shreddit-comment>
    `;
    const thread = document.getElementById('thread');
    const elements = querySelectorAll('commentText', thread);
    expect(elements).toHaveLength(1);
    expect(elements[0].textContent).toBe('Thread Comment');
  });
});
