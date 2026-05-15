/**
 * Marketing Engine — Visitor Identity & A/B Test Engine
 * Pure vanilla JS, no external dependencies.
 */
const MarketingEngine = (function () {
    'use strict';

    // =========================================================================
    // Cookie Utilities
    // =========================================================================

    /**
     * Get a cookie value by name.
     * @param {string} name
     * @returns {string|null}
     */
    function getCookie(name) {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.indexOf(name + '=') === 0) {
                return decodeURIComponent(cookie.substring(name.length + 1));
            }
        }
        return null;
    }

    /**
     * Set a cookie with a given name, value, and expiry in days.
     * @param {string} name
     * @param {string} value
     * @param {number} days
     */
    function setCookie(name, value, days) {
        var expires = new Date();
        expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000);
        document.cookie =
            name + '=' + encodeURIComponent(value) +
            ';expires=' + expires.toUTCString() +
            ';path=/';
    }

    // =========================================================================
    // Visitor Identity
    // =========================================================================

    /**
     * Validate a string as UUID v4 format (8-4-4-4-12 hex with version 4 nibble).
     * @param {string} value
     * @returns {boolean}
     */
    function isValidUUID(value) {
        if (typeof value !== 'string') return false;
        return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
    }

    /**
     * Generate a UUID v4 using crypto.getRandomValues() for proper randomness.
     * Sets version bits (4) and variant bits (8/9/a/b).
     * @returns {string}
     */
    function generateUUIDv4() {
        var bytes = new Uint8Array(16);
        crypto.getRandomValues(bytes);

        // Set version 4 (0100 in bits 4-7 of byte 6)
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        // Set variant (10xx in bits 6-7 of byte 8)
        bytes[8] = (bytes[8] & 0x3f) | 0x80;

        var hex = '';
        for (var i = 0; i < 16; i++) {
            var h = bytes[i].toString(16);
            if (h.length === 1) h = '0' + h;
            hex += h;
        }

        return (
            hex.substring(0, 8) + '-' +
            hex.substring(8, 12) + '-' +
            hex.substring(12, 16) + '-' +
            hex.substring(16, 20) + '-' +
            hex.substring(20, 32)
        );
    }

    /**
     * Get or create a visitor ID.
     * - If a valid UUID v4 cookie exists, refresh its expiry and return it.
     * - Otherwise, generate a new UUID v4, set the cookie, and return it.
     * @returns {string}
     */
    function getOrCreateVisitorId() {
        var existing = getCookie('visitor_id');
        if (existing && isValidUUID(existing)) {
            // Refresh expiry to 30 days
            setCookie('visitor_id', existing, 30);
            return existing;
        }
        // Generate new UUID v4
        var newId = generateUUIDv4();
        setCookie('visitor_id', newId, 30);
        return newId;
    }

    // =========================================================================
    // A/B Test Engine
    // =========================================================================

    /**
     * Read all A/B test assignment cookies (pattern: ab_<test_name>).
     * @returns {Object} Map of test_name → variant_name
     */
    function getAssignments() {
        var assignments = {};
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.indexOf('ab_') === 0) {
                var eqIndex = cookie.indexOf('=');
                if (eqIndex > 0) {
                    var name = cookie.substring(3, eqIndex); // strip "ab_" prefix
                    var value = decodeURIComponent(cookie.substring(eqIndex + 1));
                    if (value) {
                        assignments[name] = value;
                    }
                }
            }
        }
        return assignments;
    }

    /**
     * Assign a variant uniformly at random from the variants array.
     * @param {string} testName - Name of the test (unused but kept for API consistency)
     * @param {Array} variants - Array of variant objects with "name" property
     * @returns {string} Selected variant name
     */
    function assignVariant(testName, variants) {
        var index = Math.floor(Math.random() * variants.length);
        return variants[index].name;
    }

    /**
     * Apply variant assignments to DOM elements with data-ab-test attributes.
     * For each element, find the matching variant in data-variants JSON and
     * update the element's text content with the variant's display value.
     * @param {Object} assignments - Map of test_name → variant_name
     */
    function applyVariants(assignments) {
        var elements = document.querySelectorAll('[data-ab-test]');
        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            var testName = el.getAttribute('data-ab-test');
            var variantName = assignments[testName];
            if (!variantName) continue;

            var variantsJson = el.getAttribute('data-variants');
            if (!variantsJson) continue;

            try {
                var variants = JSON.parse(variantsJson);
                for (var j = 0; j < variants.length; j++) {
                    if (variants[j].name === variantName) {
                        el.textContent = variants[j].display;
                        break;
                    }
                }
            } catch (e) {
                // Corrupted data-variants JSON, skip this element
                console.warn('MarketingEngine: Invalid data-variants JSON on element', el);
            }
        }
    }

    /**
     * Record A/B test assignments to the server.
     * POST to /api/ab/record with retry (3 attempts, exponential backoff: 1s, 2s, 4s).
     * On final failure, log to console (variant is still displayed to visitor).
     * @param {string} visitorId
     * @param {Object} assignments - Map of test_name → variant_name
     */
    function recordAssignments(visitorId, assignments) {
        var assignmentList = [];
        for (var testName in assignments) {
            if (assignments.hasOwnProperty(testName)) {
                assignmentList.push({
                    test_name: testName,
                    variant_name: assignments[testName]
                });
            }
        }

        if (assignmentList.length === 0) return;

        var body = JSON.stringify({
            visitor_id: visitorId,
            assignments: assignmentList
        });

        function attempt(retryCount) {
            fetch('/api/ab/record', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body
            })
            .then(function (response) {
                if (!response.ok && retryCount < 3) {
                    var delay = Math.pow(2, retryCount) * 1000; // 1s, 2s, 4s
                    setTimeout(function () {
                        attempt(retryCount + 1);
                    }, delay);
                } else if (!response.ok) {
                    console.warn(
                        'MarketingEngine: Failed to record assignments after 3 retries.',
                        'Status:', response.status
                    );
                }
            })
            .catch(function (err) {
                if (retryCount < 3) {
                    var delay = Math.pow(2, retryCount) * 1000;
                    setTimeout(function () {
                        attempt(retryCount + 1);
                    }, delay);
                } else {
                    console.warn(
                        'MarketingEngine: Failed to record assignments after 3 retries.',
                        err
                    );
                }
            });
        }

        attempt(0);
    }

    /**
     * Check if a variant name is valid for a given test's data-variants list.
     * @param {string} variantName
     * @param {Array} variants - Array of variant objects with "name" property
     * @returns {boolean}
     */
    function isValidVariantForTest(variantName, variants) {
        for (var i = 0; i < variants.length; i++) {
            if (variants[i].name === variantName) {
                return true;
            }
        }
        return false;
    }

    // =========================================================================
    // Analytics Tracker
    // =========================================================================

    var eventQueue = [];
    var MAX_QUEUE_SIZE = 100;
    var FLUSH_THRESHOLD = 20;
    var FLUSH_INTERVAL_MS = 5000;
    var OFFLINE_STORAGE_KEY = 'ramp_offline_events';
    var MAX_OFFLINE_EVENTS = 50;
    var OFFLINE_TTL_MS = 72 * 60 * 60 * 1000; // 72 hours

    /** Current visitor ID — set during init(). */
    var currentVisitorId = null;

    /**
     * Track an analytics event.
     * Adds event to the queue with visitor_id, page_path, and timestamp.
     * Triggers flush if queue reaches FLUSH_THRESHOLD.
     * @param {string} type - Event type (page_view, click, signup)
     * @param {Object} [data] - Optional event data
     */
    function trackEvent(type, data) {
        if (!currentVisitorId) return;

        var event = {
            visitor_id: currentVisitorId,
            event_type: type,
            event_data: data || {},
            page_path: window.location.pathname,
            timestamp: new Date().toISOString()
        };

        // If queue is at max, drop oldest event
        if (eventQueue.length >= MAX_QUEUE_SIZE) {
            eventQueue.shift();
        }

        eventQueue.push(event);

        // Auto-flush at threshold
        if (eventQueue.length >= FLUSH_THRESHOLD) {
            flushQueue();
        }
    }

    /**
     * Flush the event queue by sending a batch to the server.
     * On success: clears sent events from queue.
     * On failure: stores events in localStorage for offline retry.
     */
    function flushQueue() {
        if (eventQueue.length === 0) return;

        var eventsToSend = eventQueue.slice();
        eventQueue = [];

        var body = JSON.stringify({ events: eventsToSend });

        fetch('/api/analytics/events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body
        })
        .then(function (response) {
            if (!response.ok) {
                // Store failed events in offline queue
                storeOfflineEvents(eventsToSend);
            }
            // On success: events already removed from queue
        })
        .catch(function () {
            // Network error — store in offline queue
            storeOfflineEvents(eventsToSend);
        });
    }

    /**
     * Store events in localStorage for offline retry.
     * Enforces max 50 events, drops oldest if exceeded.
     * @param {Array} events - Events to store
     */
    function storeOfflineEvents(events) {
        try {
            var existing = getOfflineQueue();
            var combined = existing.concat(events);

            // Drop oldest events if exceeding max
            if (combined.length > MAX_OFFLINE_EVENTS) {
                combined = combined.slice(combined.length - MAX_OFFLINE_EVENTS);
            }

            localStorage.setItem(OFFLINE_STORAGE_KEY, JSON.stringify(combined));
        } catch (e) {
            // localStorage unavailable or full — discard silently
        }
    }

    /**
     * Read the offline event queue from localStorage.
     * @returns {Array} Stored events or empty array
     */
    function getOfflineQueue() {
        try {
            var stored = localStorage.getItem(OFFLINE_STORAGE_KEY);
            if (!stored) return [];
            return JSON.parse(stored);
        } catch (e) {
            return [];
        }
    }

    /**
     * Retry sending stored offline events on page load.
     * On second failure: discard events older than 72 hours.
     */
    function retryOfflineEvents() {
        var offlineEvents = getOfflineQueue();
        if (offlineEvents.length === 0) return;

        // Clear storage before attempting send
        try {
            localStorage.removeItem(OFFLINE_STORAGE_KEY);
        } catch (e) {
            // Ignore
        }

        var body = JSON.stringify({ events: offlineEvents });

        fetch('/api/analytics/events', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body
        })
        .then(function (response) {
            if (!response.ok) {
                // Second failure — discard events older than 72 hours
                var now = Date.now();
                var fresh = [];
                for (var i = 0; i < offlineEvents.length; i++) {
                    var eventTime = new Date(offlineEvents[i].timestamp).getTime();
                    if (now - eventTime < OFFLINE_TTL_MS) {
                        fresh.push(offlineEvents[i]);
                    }
                }
                // Store only fresh events, respecting max limit
                if (fresh.length > MAX_OFFLINE_EVENTS) {
                    fresh = fresh.slice(fresh.length - MAX_OFFLINE_EVENTS);
                }
                if (fresh.length > 0) {
                    try {
                        localStorage.setItem(OFFLINE_STORAGE_KEY, JSON.stringify(fresh));
                    } catch (e) {
                        // Ignore
                    }
                }
            }
            // On success: events sent, storage already cleared
        })
        .catch(function () {
            // Network error on retry — discard events older than 72 hours
            var now = Date.now();
            var fresh = [];
            for (var i = 0; i < offlineEvents.length; i++) {
                var eventTime = new Date(offlineEvents[i].timestamp).getTime();
                if (now - eventTime < OFFLINE_TTL_MS) {
                    fresh.push(offlineEvents[i]);
                }
            }
            if (fresh.length > MAX_OFFLINE_EVENTS) {
                fresh = fresh.slice(fresh.length - MAX_OFFLINE_EVENTS);
            }
            if (fresh.length > 0) {
                try {
                    localStorage.setItem(OFFLINE_STORAGE_KEY, JSON.stringify(fresh));
                } catch (e) {
                    // Ignore
                }
            }
        });
    }

    /**
     * Set up auto-flush interval and beforeunload handler.
     */
    function setupAutoFlush() {
        // Flush every 5 seconds
        setInterval(flushQueue, FLUSH_INTERVAL_MS);

        // Flush on page unload using sendBeacon for reliability
        window.addEventListener('beforeunload', function () {
            if (eventQueue.length === 0) return;

            var body = JSON.stringify({ events: eventQueue });

            if (navigator.sendBeacon) {
                navigator.sendBeacon('/api/analytics/events', new Blob([body], { type: 'application/json' }));
            } else {
                // Fallback to synchronous fetch (best effort)
                fetch('/api/analytics/events', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: body,
                    keepalive: true
                });
            }

            eventQueue = [];
        });
    }

    /**
     * Set up click tracking via event delegation.
     * Tracks clicks on elements with data-track-click attribute.
     */
    function setupClickTracking() {
        document.addEventListener('click', function (e) {
            var target = e.target;
            // Walk up the DOM to find the closest element with data-track-click
            while (target && target !== document) {
                if (target.hasAttribute && target.hasAttribute('data-track-click')) {
                    var trackId = target.getAttribute('data-track-click');
                    trackEvent('click', {
                        element_id: trackId,
                        tag: target.tagName.toLowerCase(),
                        text: (target.textContent || '').substring(0, 100).trim()
                    });
                    return;
                }
                target = target.parentNode;
            }
        });
    }

    /**
     * Set up form submit tracking for waitlist signup forms.
     * Tracks signup event on forms with action="/waitlist/signup".
     */
    function setupFormTracking() {
        document.addEventListener('submit', function (e) {
            var form = e.target;
            if (form && form.tagName === 'FORM' && form.getAttribute('action') === '/waitlist/signup') {
                trackEvent('signup', {
                    source_page: window.location.pathname
                });
            }
        });
    }

    // =========================================================================
    // Page Load Initialization
    // =========================================================================

    /**
     * Initialize the marketing engine on page load.
     * - Get/create visitor ID
     * - Read page test configuration from DOM
     * - For each test: check cookie, validate, assign if needed
     * - Apply variants to DOM
     * - Record new assignments to server
     * - Initialize analytics tracking
     */
    function init() {
        var visitorId = getOrCreateVisitorId();
        currentVisitorId = visitorId;

        var existingAssignments = getAssignments();
        var finalAssignments = {};
        var newAssignments = {};

        // Read page's test configuration from DOM elements with data-ab-test
        var elements = document.querySelectorAll('[data-ab-test]');
        var testsOnPage = {};

        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            var testName = el.getAttribute('data-ab-test');
            if (testsOnPage[testName]) continue; // Already processed this test

            var variantsJson = el.getAttribute('data-variants');
            if (!variantsJson) continue;

            try {
                var variants = JSON.parse(variantsJson);
                testsOnPage[testName] = variants;
            } catch (e) {
                console.warn('MarketingEngine: Invalid data-variants JSON for test:', testName);
                continue;
            }
        }

        // For each test on the page, check cookie and assign if needed
        for (var testName in testsOnPage) {
            if (!testsOnPage.hasOwnProperty(testName)) continue;

            var variants = testsOnPage[testName];
            var cookieVariant = existingAssignments[testName];

            if (cookieVariant && isValidVariantForTest(cookieVariant, variants)) {
                // Valid assignment exists — use it, refresh cookie
                finalAssignments[testName] = cookieVariant;
                setCookie('ab_' + testName, cookieVariant, 30);
            } else {
                // No cookie, or corrupted/invalid cookie — assign new variant
                var selected = assignVariant(testName, variants);
                finalAssignments[testName] = selected;
                setCookie('ab_' + testName, selected, 30);
                newAssignments[testName] = selected;
            }
        }

        // Apply variants to DOM
        applyVariants(finalAssignments);

        // Record new assignments to server (only newly assigned ones)
        if (Object.keys(newAssignments).length > 0) {
            recordAssignments(visitorId, newAssignments);
        }

        // --- Analytics Initialization ---
        // Track page_view with variant data
        trackEvent('page_view', { variants: finalAssignments });

        // Set up auto-flush (5s interval + beforeunload)
        setupAutoFlush();

        // Set up click tracking via event delegation
        setupClickTracking();

        // Set up form submit tracking
        setupFormTracking();

        // Retry any offline events from previous sessions
        retryOfflineEvents();
    }

    // =========================================================================
    // Public API
    // =========================================================================

    return { init: init };
})();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function () {
    MarketingEngine.init();
});
