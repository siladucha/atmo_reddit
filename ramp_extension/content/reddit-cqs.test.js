import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { postCQSCheck } from './reddit-cqs.js';
// Import selectors to ensure globalThis.RAMP.selectors is available
import './reddit-selectors.js';

describe('postCQSCheck', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // Default: simulate being on the submit page
    Object.defineProperty(window, 'location', {
      value: {
        href: 'https://www.reddit.com/r/WhatIsMyCQS/submit',
        pathname: '/r/WhatIsMyCQS/submit',
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('result object shape', () => {
    it('returns complete result object on error', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result).toHaveProperty('status');
      expect(result).toHaveProperty('raw_output');
      expect(result).toHaveProperty('post_url');
      expect(result).toHaveProperty('execution_metadata');
      expect(result.execution_metadata).toHaveProperty('duration_ms');
      expect(result.execution_metadata).toHaveProperty('reddit_variant');
      expect(result.execution_metadata).toHaveProperty('timestamp');
      expect(result).toHaveProperty('error_code');
      expect(result).toHaveProperty('error_details');
    });

    it('execution_metadata.reddit_variant is detected', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.execution_metadata.reddit_variant).toBe('shreddit');
    });

    it('execution_metadata.timestamp is valid ISO string', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(() => new Date(result.execution_metadata.timestamp)).not.toThrow();
      expect(new Date(result.execution_metadata.timestamp).toISOString()).toBe(
        result.execution_metadata.timestamp
      );
    });
  });

  describe('submit page errors', () => {
    it('returns submit_failed when title input not found', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <div>Empty submit page without form elements</div>
      `;

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('submit_failed');
      expect(result.error_details).toContain('title input');
      expect(result.raw_output).toBeNull();
      expect(result.post_url).toBeNull();
    });

    it('returns submit_failed when body text area not found', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <textarea name="title"></textarea>
      `;

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('submit_failed');
      expect(result.error_details).toContain('body text area');
    });

    it('returns submit_failed when submit button not found', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <textarea name="title"></textarea>
        <div contenteditable="true" role="textbox"></div>
      `;

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('submit_failed');
      expect(result.error_details).toContain('submit button');
    });
  });

  describe('post submission flow', () => {
    it('fills title and body with CQS text', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <textarea name="title"></textarea>
        <div contenteditable="true" role="textbox"></div>
        <button type="submit">Post</button>
      `;

      const titleInput = document.querySelector('textarea[name="title"]');
      const bodyArea = document.querySelector('div[contenteditable="true"]');

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(2_000);

      expect(titleInput.value).toBe('What is my CQS?');
      expect(bodyArea.textContent).toBe('What is my CQS?');

      // Let it complete (will timeout waiting for redirect)
      await vi.advanceTimersByTimeAsync(100_000);
      await resultPromise;
    });

    it('returns submit_failed when redirect does not happen', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <textarea name="title"></textarea>
        <div contenteditable="true" role="textbox"></div>
        <button type="submit">Post</button>
      `;

      const resultPromise = postCQSCheck();
      // Advance through: element waits + submit + redirect wait + automod wait
      await vi.advanceTimersByTimeAsync(120_000);
      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('submit_failed');
      expect(result.error_details).toContain('redirect');
    });
  });

  describe('AutoModerator reply detection', () => {
    it('returns timeout when no bot reply within 90s', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <textarea name="title"></textarea>
        <div contenteditable="true" role="textbox"></div>
        <button type="submit">Post</button>
      `;

      // Simulate being on the post page after submit
      Object.defineProperty(window, 'location', {
        value: {
          href: 'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/',
          pathname: '/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/',
        },
        writable: true,
        configurable: true,
      });

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(120_000);
      const result = await resultPromise;

      expect(result.status).toBe('timeout');
      expect(result.raw_output).toBeNull();
      expect(result.post_url).toBeTruthy();
      expect(result.error_code).toBeNull();
    });

    it('detects AutoModerator reply in shreddit variant', async () => {
      // Start already on the post page (simulate post was already submitted)
      Object.defineProperty(window, 'location', {
        value: {
          href: 'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/',
          pathname: '/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/',
        },
        writable: true,
        configurable: true,
      });

      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <textarea name="title"></textarea>
        <div contenteditable="true" role="textbox"></div>
        <button type="submit">Post</button>
      `;

      // Simulate submit + bot reply after 5 seconds
      const submitBtn = document.querySelector('button[type="submit"]');
      submitBtn.addEventListener('click', () => {
        setTimeout(() => {
          const comment = document.createElement('shreddit-comment');
          comment.setAttribute('author', 'AutoModerator');
          comment.setAttribute('thingid', 't1_bot123');
          const p = document.createElement('p');
          p.textContent = 'Your current CQS is LOW.';
          comment.appendChild(p);
          document.body.appendChild(comment);
        }, 5000);
      });

      const resultPromise = postCQSCheck();
      // Advance: element wait + submit + redirect check + initial delay + bot reply (5s) + poll (3s)
      await vi.advanceTimersByTimeAsync(15_000);
      const result = await resultPromise;

      expect(result.status).toBe('completed');
      expect(result.raw_output).toContain('CQS');
      expect(result.raw_output).toContain('LOW');
      expect(result.error_code).toBeNull();
    });

    it('detects AutoModerator reply in old reddit variant', async () => {
      // Simulate already being on the post page (after redirect)
      Object.defineProperty(window, 'location', {
        value: {
          href: 'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/',
          pathname: '/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/',
        },
        writable: true,
        configurable: true,
      });

      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div id="newlink">
          <textarea name="title"></textarea>
          <textarea name="text"></textarea>
          <button type="submit">Submit</button>
        </div>
      `;

      // Simulate: after submit click, bot reply appears after a delay
      const submitBtn = document.querySelector('button[type="submit"]');
      submitBtn.addEventListener('click', () => {
        setTimeout(() => {
          const comment = document.createElement('div');
          comment.className = 'comment';
          comment.innerHTML = `
            <a class="author">AutoModerator</a>
            <div class="usertext-body">
              <p>Your current CQS is MEDIUM.</p>
            </div>
          `;
          document.body.appendChild(comment);
        }, 4000);
      });

      const resultPromise = postCQSCheck();
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.status).toBe('completed');
      expect(result.raw_output).toContain('CQS');
      expect(result.raw_output).toContain('MEDIUM');
    });
  });

  describe('globalThis.RAMP.actions namespace', () => {
    it('exposes postCQSCheck on globalThis.RAMP.actions', () => {
      expect(globalThis.RAMP.actions).toBeDefined();
      expect(globalThis.RAMP.actions.postCQSCheck).toBe(postCQSCheck);
    });
  });
});
