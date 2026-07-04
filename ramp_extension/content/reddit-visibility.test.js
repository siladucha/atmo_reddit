import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { checkSubmissionVisibility, extractPostId } from './reddit-visibility.js';
import './reddit-selectors.js';

describe('extractPostId', () => {
  it('extracts post ID from full Reddit URL', () => {
    expect(extractPostId('https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/what_is_my_cqs/')).toBe('abc123');
  });

  it('extracts post ID from URL without trailing slash', () => {
    expect(extractPostId('https://www.reddit.com/r/test/comments/xyz789/my_post')).toBe('xyz789');
  });

  it('extracts post ID from short URL', () => {
    expect(extractPostId('https://reddit.com/comments/def456/')).toBe('def456');
  });

  it('returns null for empty string', () => {
    expect(extractPostId('')).toBeNull();
  });

  it('returns null for null input', () => {
    expect(extractPostId(null)).toBeNull();
  });

  it('returns null for URL without /comments/', () => {
    expect(extractPostId('https://www.reddit.com/r/test/new/')).toBeNull();
  });

  it('extracts alphanumeric post IDs', () => {
    expect(extractPostId('https://www.reddit.com/r/sysadmin/comments/1uge4ov/test_post/')).toBe('1uge4ov');
  });
});

describe('checkSubmissionVisibility', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers({ shouldAdvanceTime: true });

    // Default: simulate being on the /new feed page
    Object.defineProperty(window, 'location', {
      value: {
        href: 'https://www.reddit.com/r/WhatIsMyCQS/new/',
        pathname: '/r/WhatIsMyCQS/new/',
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('input validation', () => {
    it('returns error when postUrl is empty', async () => {
      const result = await checkSubmissionVisibility('', 'WhatIsMyCQS');
      expect(result.status).toBe('error');
      expect(result.error_code).toBe('invalid_input');
      expect(result.error_details).toContain('postUrl');
      expect(result.visible).toBe(false);
    });

    it('returns error when subreddit is empty', async () => {
      const result = await checkSubmissionVisibility('https://reddit.com/r/test/comments/abc123/', '');
      expect(result.status).toBe('error');
      expect(result.error_code).toBe('invalid_input');
      expect(result.error_details).toContain('subreddit');
    });

    it('returns error when postUrl has no valid post ID', async () => {
      const result = await checkSubmissionVisibility('https://reddit.com/r/test/new/', 'test');
      expect(result.status).toBe('error');
      expect(result.error_code).toBe('invalid_input');
      expect(result.error_details).toContain('post ID');
    });
  });

  describe('result object shape', () => {
    it('returns complete result object', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      const resultPromise = checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test/',
        'WhatIsMyCQS'
      );
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result).toHaveProperty('status');
      expect(result).toHaveProperty('visible');
      expect(result).toHaveProperty('checked_posts');
      expect(result).toHaveProperty('execution_metadata');
      expect(result.execution_metadata).toHaveProperty('duration_ms');
      expect(result.execution_metadata).toHaveProperty('reddit_variant');
      expect(result.execution_metadata).toHaveProperty('timestamp');
      expect(result).toHaveProperty('error_code');
      expect(result).toHaveProperty('error_details');
    });

    it('execution_metadata.reddit_variant is detected', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      const resultPromise = checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test/',
        'WhatIsMyCQS'
      );
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.execution_metadata.reddit_variant).toBe('shreddit');
    });

    it('execution_metadata.timestamp is valid ISO string', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      const resultPromise = checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test/',
        'WhatIsMyCQS'
      );
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(() => new Date(result.execution_metadata.timestamp)).not.toThrow();
      expect(new Date(result.execution_metadata.timestamp).toISOString()).toBe(
        result.execution_metadata.timestamp
      );
    });
  });

  describe('feed loading', () => {
    it('returns error when feed does not load within 15s', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <div>Empty page with no posts</div>
      `;

      const resultPromise = checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test/',
        'WhatIsMyCQS'
      );
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await resultPromise;

      expect(result.status).toBe('error');
      expect(result.error_code).toBe('feed_load_timeout');
      expect(result.visible).toBe(false);
      expect(result.checked_posts).toBe(0);
    });
  });

  describe('post visibility detection — shreddit variant', () => {
    it('returns visible=true when post found by permalink attribute', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-post permalink="/r/WhatIsMyCQS/comments/abc123/test_post/"></shreddit-post>
        <shreddit-post permalink="/r/WhatIsMyCQS/comments/def456/other_post/"></shreddit-post>
        <shreddit-post permalink="/r/WhatIsMyCQS/comments/ghi789/third_post/"></shreddit-post>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test_post/',
        'WhatIsMyCQS'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(true);
      expect(result.checked_posts).toBeGreaterThanOrEqual(1);
      expect(result.error_code).toBeNull();
    });

    it('returns visible=false when post not found in feed', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-post permalink="/r/WhatIsMyCQS/comments/def456/other_post/"></shreddit-post>
        <shreddit-post permalink="/r/WhatIsMyCQS/comments/ghi789/third_post/"></shreddit-post>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test_post/',
        'WhatIsMyCQS'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(false);
      expect(result.checked_posts).toBe(2);
      expect(result.error_code).toBeNull();
    });

    it('detects post by link href within post element', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-post>
          <a slot="full-post-link" href="/r/WhatIsMyCQS/comments/abc123/test/"></a>
        </shreddit-post>
        <shreddit-post>
          <a slot="full-post-link" href="/r/WhatIsMyCQS/comments/other999/other/"></a>
        </shreddit-post>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/WhatIsMyCQS/comments/abc123/test/',
        'WhatIsMyCQS'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(true);
    });

    it('counts all posts scanned', async () => {
      document.body.innerHTML = `
        <shreddit-app></shreddit-app>
        <shreddit-post permalink="/r/test/comments/a1/post1/"></shreddit-post>
        <shreddit-post permalink="/r/test/comments/a2/post2/"></shreddit-post>
        <shreddit-post permalink="/r/test/comments/a3/post3/"></shreddit-post>
        <shreddit-post permalink="/r/test/comments/a4/post4/"></shreddit-post>
        <shreddit-post permalink="/r/test/comments/a5/post5/"></shreddit-post>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/test/comments/nothere/missing/',
        'test'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(false);
      expect(result.checked_posts).toBe(5);
    });
  });

  describe('post visibility detection — old reddit variant', () => {
    it('returns visible=true when post found by data-permalink', async () => {
      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div id="siteTable">
          <div class="thing" data-fullname="t3_abc123" data-permalink="/r/test/comments/abc123/post/">
            <a class="title" href="/r/test/comments/abc123/post/">My Post</a>
          </div>
          <div class="thing" data-fullname="t3_def456" data-permalink="/r/test/comments/def456/other/">
            <a class="title" href="/r/test/comments/def456/other/">Other Post</a>
          </div>
        </div>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/test/comments/abc123/post/',
        'test'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(true);
      expect(result.execution_metadata.reddit_variant).toBe('old');
    });

    it('returns visible=false when post not in old reddit feed', async () => {
      document.body.innerHTML = `
        <div id="header-bottom-left"></div>
        <div id="siteTable">
          <div class="thing" data-fullname="t3_def456" data-permalink="/r/test/comments/def456/other/">
            <a class="title" href="/r/test/comments/def456/other/">Other Post</a>
          </div>
        </div>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/test/comments/abc123/post/',
        'test'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(false);
      expect(result.checked_posts).toBe(1);
    });
  });

  describe('post visibility detection — redesign variant', () => {
    it('returns visible=true when post found via link href', async () => {
      document.body.innerHTML = `
        <div data-testid="post-container">
          <a data-click-id="body" href="/r/test/comments/abc123/post/">My Post</a>
        </div>
        <div data-testid="post-container">
          <a data-click-id="body" href="/r/test/comments/def456/other/">Other</a>
        </div>
      `;

      const result = await checkSubmissionVisibility(
        'https://www.reddit.com/r/test/comments/abc123/post/',
        'test'
      );

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(true);
      expect(result.execution_metadata.reddit_variant).toBe('redesign');
    });
  });

  describe('delayed feed loading', () => {
    it('waits for posts to appear before scanning', async () => {
      document.body.innerHTML = '<shreddit-app></shreddit-app>';

      // Simulate posts appearing after 3 seconds
      setTimeout(() => {
        const post = document.createElement('shreddit-post');
        post.setAttribute('permalink', '/r/test/comments/abc123/found/');
        document.body.appendChild(post);
      }, 3000);

      const resultPromise = checkSubmissionVisibility(
        'https://www.reddit.com/r/test/comments/abc123/found/',
        'test'
      );
      await vi.advanceTimersByTimeAsync(5_000);
      const result = await resultPromise;

      expect(result.status).toBe('completed');
      expect(result.visible).toBe(true);
    });
  });

  describe('globalThis.RAMP.actions namespace', () => {
    it('exposes checkSubmissionVisibility on globalThis.RAMP.actions', () => {
      expect(globalThis.RAMP.actions).toBeDefined();
      expect(globalThis.RAMP.actions.checkSubmissionVisibility).toBe(checkSubmissionVisibility);
    });
  });
});
