import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { postComment } from './reddit-comment.js';
// Import selectors to ensure globalThis.RAMP.selectors is available
import './reddit-selectors.js';

describe('postComment', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('error handling — selector system unavailable', () => {
    it('returns error when RAMP selectors not available', async () => {
      const savedSelectors = globalThis.RAMP.selectors;
      globalThis.RAMP.selectors = undefined;

      const result = await postComment('https://www.reddit.com/r/test/comments/abc123/title/', 'Hello');

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('dom_structure_changed');
      expect(result.error_details).toContain('selector system not available');
      expect(result.permalink).toBeNull();
      expect(result.comment_id).toBeNull();
      expect(result.posted_at).toBeNull();

      globalThis.RAMP.selectors = savedSelectors;
    });
  });

  describe('thread blocked detection', () => {
    it('returns blocked when thread has locked banner (shreddit)', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-post locked></shreddit-post>
      `;

      const result = await postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'Hello world'
      );

      expect(result.status).toBe('blocked');
      expect(result.error_code).toBe('thread_locked');
      expect(result.permalink).toBeNull();
    });

    it('returns blocked when thread has locked text', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <div>Comments are locked on this post</div>
      `;

      const result = await postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'Hello world'
      );

      expect(result.status).toBe('blocked');
      expect(result.error_code).toBe('thread_locked');
    });

    it('returns blocked for archived thread (old reddit)', async () => {
      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div class="archived-infobar">This is an archived post</div>
      `;

      const result = await postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'Hello world'
      );

      expect(result.status).toBe('blocked');
      expect(result.error_code).toBe('thread_locked');
    });
  });

  describe('top-level comment posting', () => {
    it('returns dom_structure_changed when text area not found', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <div>A thread without comment box</div>
      `;

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'My comment'
      );

      // Advance timers past the waitForElement timeout (10s)
      await vi.advanceTimersByTimeAsync(11_000);

      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('dom_structure_changed');
      expect(result.error_details).toContain('text area not found');
    });

    it('returns dom_structure_changed when submit button not found', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-composer>
          <textarea></textarea>
        </shreddit-composer>
      `;

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'My comment'
      );

      // Wait for text area detection + brief delay
      await vi.advanceTimersByTimeAsync(500);

      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('dom_structure_changed');
      expect(result.error_details).toContain('Submit button not found');
    });

    it('returns submit_timeout when comment does not appear after submit', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-composer>
          <textarea></textarea>
        </shreddit-composer>
        <button type="submit" slot="submit-button">Submit</button>
      `;

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'My comment'
      );

      // Advance past textarea wait + delay + submit timeout (30s)
      await vi.advanceTimersByTimeAsync(35_000);

      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('submit_timeout');
      expect(result.error_details).toContain('30s');
    });

    it('posts successfully and returns permalink for shreddit', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-composer>
          <textarea></textarea>
        </shreddit-composer>
        <button type="submit" slot="submit-button">Submit</button>
      `;

      // Simulate: after submit click, new comment appears in DOM
      const submitBtn = document.querySelector('button[type="submit"]');
      submitBtn.addEventListener('click', () => {
        setTimeout(() => {
          const comment = document.createElement('shreddit-comment');
          comment.setAttribute('thingid', 't1_newid123');
          const p = document.createElement('p');
          p.textContent = 'Test comment here';
          comment.appendChild(p);
          document.body.appendChild(comment);
        }, 500);
      });

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'Test comment here'
      );

      // Advance time: 300ms poll + 200ms post-input delay + 500ms for comment to appear
      await vi.advanceTimersByTimeAsync(2_000);

      const result = await resultPromise;

      expect(result.status).toBe('posted');
      expect(result.comment_id).toBe('t1_newid123');
      expect(result.posted_at).toBeTruthy();
      expect(result.error_code).toBeNull();
    });
  });

  describe('reply to comment', () => {
    it('returns error when target comment not found', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <div>No comments here</div>
      `;

      const result = await postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'My reply',
        't1_nonexistent'
      );

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('dom_structure_changed');
      expect(result.error_details).toContain('Could not find comment element');
    });

    it('finds shreddit comment by thingid with t1_ prefix', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-comment thingid="t1_parent123">
          <button slot="reply-button">Reply</button>
        </shreddit-comment>
      `;

      // The reply button click won't produce a textarea in this simple test,
      // so we expect an error about editor not appearing
      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc123/title/',
        'My reply',
        't1_parent123'
      );

      await vi.advanceTimersByTimeAsync(6_000);

      const result = await resultPromise;

      // reply button was found and clicked, but editor didn't appear
      expect(result.status).toBe('error');
      expect(result.error_details).toContain('reply editor did not appear');
    });

    it('finds comment by bare ID (without t1_ prefix)', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-comment thingid="t1_abc456">
          <button slot="reply-button">Reply</button>
        </shreddit-comment>
      `;

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/xyz/title/',
        'Reply text',
        'abc456'
      );

      await vi.advanceTimersByTimeAsync(6_000);

      const result = await resultPromise;

      // Comment was found (would fail with "Could not find comment" otherwise)
      expect(result.error_details).toContain('reply editor did not appear');
    });
  });

  describe('text input handling', () => {
    it('sets text in textarea element', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-composer>
          <textarea></textarea>
        </shreddit-composer>
        <button type="submit" slot="submit-button">Submit</button>
      `;

      const textarea = document.querySelector('textarea');
      let inputFired = false;
      textarea.addEventListener('input', () => { inputFired = true; });

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc/title/',
        'Text content'
      );

      // Advance past textarea detection
      await vi.advanceTimersByTimeAsync(500);

      // textarea value should be set
      expect(textarea.value).toBe('Text content');
      expect(inputFired).toBe(true);

      // Advance past timeout to complete the promise
      await vi.advanceTimersByTimeAsync(35_000);
      await resultPromise;
    });

    it('sets text in contenteditable element', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-composer>
          <div contenteditable="true"></div>
        </shreddit-composer>
        <button type="submit" slot="submit-button">Submit</button>
      `;

      const editable = document.querySelector('div[contenteditable]');
      let inputFired = false;
      editable.addEventListener('input', () => { inputFired = true; });

      const resultPromise = postComment(
        'https://www.reddit.com/r/test/comments/abc/title/',
        'Editable content'
      );

      // Advance past textarea detection
      await vi.advanceTimersByTimeAsync(500);

      expect(editable.textContent).toBe('Editable content');
      expect(inputFired).toBe(true);

      // Advance past timeout to complete the promise
      await vi.advanceTimersByTimeAsync(35_000);
      await resultPromise;
    });
  });

  describe('result object shape', () => {
    it('always returns complete result object on error', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-post locked></shreddit-post>
      `;

      const result = await postComment(
        'https://www.reddit.com/r/test/comments/abc/t/',
        'Hello'
      );

      expect(result).toHaveProperty('status');
      expect(result).toHaveProperty('permalink');
      expect(result).toHaveProperty('comment_id');
      expect(result).toHaveProperty('posted_at');
      expect(result).toHaveProperty('error_code');
      expect(result).toHaveProperty('error_details');
    });
  });

  describe('globalThis.RAMP.actions namespace', () => {
    it('exposes postComment on globalThis.RAMP.actions', () => {
      expect(globalThis.RAMP.actions).toBeDefined();
      expect(globalThis.RAMP.actions.postComment).toBe(postComment);
    });
  });
});
