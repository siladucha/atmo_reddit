/**
 * RAMP Admin — Searchable Dropdown (Combobox)
 *
 * Progressive enhancement: converts a plain <select> into a searchable
 * combobox with keyboard navigation. Falls back to native <select> if JS
 * is disabled.
 *
 * Usage:
 *   <select data-searchable>
 *     <option value="">All</option>
 *     <option value="r/yoga">r/yoga</option>
 *     ...
 *   </select>
 *
 * Or initialize programmatically:
 *   SearchableDropdown.init(selectElement, options?)
 *
 * Options:
 *   placeholder  — input placeholder text (default: "Type to filter...")
 *   maxHeight    — dropdown max-height in px (default: 256)
 *
 * Accessibility: role="combobox", aria-expanded, aria-activedescendant,
 *                aria-controls, role="listbox" on dropdown, role="option" on items.
 *
 * Dark theme: bg-slate-800 dropdown, border-slate-600 input, text-gray-200.
 */

(function () {
  'use strict';

  var instances = [];

  // ─── Utility ──────────────────────────────────────────────────────────────

  function generateId() {
    return 'sd-' + Math.random().toString(36).slice(2, 9);
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ─── SearchableDropdown Class ─────────────────────────────────────────────

  function SearchableDropdown(selectEl, opts) {
    opts = opts || {};
    this.selectEl = selectEl;
    this.placeholder = opts.placeholder || 'Type to filter...';
    this.maxHeight = opts.maxHeight || 256;
    this.id = generateId();
    this.isOpen = false;
    this.activeIndex = -1;
    this.filteredOptions = [];

    this._buildDOM();
    this._bindEvents();
    this._syncFromSelect();
  }

  SearchableDropdown.prototype._buildDOM = function () {
    var self = this;

    // Hide original select (keep in DOM for form submission / noscript fallback)
    this.selectEl.style.display = 'none';
    this.selectEl.setAttribute('aria-hidden', 'true');
    this.selectEl.tabIndex = -1;

    // Wrapper
    this.wrapper = document.createElement('div');
    this.wrapper.className = 'searchable-dropdown-wrapper';
    this.wrapper.style.cssText = 'position:relative;display:inline-block;width:100%;';

    // Input
    this.input = document.createElement('input');
    this.input.type = 'text';
    this.input.placeholder = this.placeholder;
    this.input.autocomplete = 'off';
    this.input.setAttribute('role', 'combobox');
    this.input.setAttribute('aria-expanded', 'false');
    this.input.setAttribute('aria-controls', this.id + '-listbox');
    this.input.setAttribute('aria-autocomplete', 'list');
    this.input.setAttribute('aria-haspopup', 'listbox');
    this.input.className = 'searchable-dropdown-input';
    this.input.style.cssText =
      'width:100%;padding:6px 32px 6px 10px;border-radius:6px;' +
      'background:#1e293b;border:1px solid #475569;color:#e2e8f0;' +
      'font-size:13px;line-height:1.5;outline:none;transition:border-color 0.15s;';

    // Chevron icon
    this.chevron = document.createElement('span');
    this.chevron.innerHTML = '<svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" style="color:#94a3b8;"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>';
    this.chevron.style.cssText =
      'position:absolute;right:8px;top:50%;transform:translateY(-50%);pointer-events:none;display:flex;';

    // Dropdown listbox
    this.listbox = document.createElement('ul');
    this.listbox.id = this.id + '-listbox';
    this.listbox.setAttribute('role', 'listbox');
    this.listbox.style.cssText =
      'display:none;position:absolute;top:calc(100% + 4px);left:0;right:0;' +
      'max-height:' + this.maxHeight + 'px;overflow-y:auto;' +
      'background:#1e293b;border:1px solid #475569;border-radius:6px;' +
      'box-shadow:0 10px 25px -5px rgba(0,0,0,0.5);z-index:100;' +
      'list-style:none;margin:0;padding:4px 0;';

    // Assemble
    this.wrapper.appendChild(this.input);
    this.wrapper.appendChild(this.chevron);
    this.wrapper.appendChild(this.listbox);
    this.selectEl.parentNode.insertBefore(this.wrapper, this.selectEl.nextSibling);
  };

  SearchableDropdown.prototype._bindEvents = function () {
    var self = this;

    // Focus styling
    this.input.addEventListener('focus', function () {
      self.input.style.borderColor = '#6366f1';
      self.open();
    });

    this.input.addEventListener('blur', function () {
      self.input.style.borderColor = '#475569';
      // Delay close so click on option registers
      setTimeout(function () { self.close(); }, 150);
    });

    // Typing filters
    this.input.addEventListener('input', function () {
      self._filter(self.input.value);
      if (!self.isOpen) self.open();
    });

    // Keyboard navigation
    this.input.addEventListener('keydown', function (e) {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          if (!self.isOpen) { self.open(); return; }
          self._moveActive(1);
          break;
        case 'ArrowUp':
          e.preventDefault();
          if (!self.isOpen) { self.open(); return; }
          self._moveActive(-1);
          break;
        case 'Enter':
          e.preventDefault();
          if (self.isOpen && self.activeIndex >= 0) {
            self._selectOption(self.activeIndex);
          }
          break;
        case 'Escape':
          e.preventDefault();
          self.close();
          self.input.blur();
          break;
        case 'Tab':
          self.close();
          break;
      }
    });

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (!self.wrapper.contains(e.target)) {
        self.close();
      }
    });
  };

  SearchableDropdown.prototype._syncFromSelect = function () {
    var self = this;
    this.options = [];

    var opts = this.selectEl.options;
    for (var i = 0; i < opts.length; i++) {
      this.options.push({
        value: opts[i].value,
        label: opts[i].textContent.trim(),
        selected: opts[i].selected
      });
    }

    // Set input to currently selected value label
    var selected = this.options.filter(function (o) { return o.selected; })[0];
    if (selected && selected.value) {
      this.input.value = selected.label;
    }

    this.filteredOptions = this.options.slice();
    this._renderOptions();
  };

  SearchableDropdown.prototype._filter = function (query) {
    var q = query.toLowerCase().trim();
    if (!q) {
      this.filteredOptions = this.options.slice();
    } else {
      this.filteredOptions = this.options.filter(function (o) {
        return o.label.toLowerCase().indexOf(q) !== -1;
      });
    }
    this.activeIndex = -1;
    this._renderOptions();
  };

  SearchableDropdown.prototype._renderOptions = function () {
    var self = this;
    this.listbox.innerHTML = '';

    if (this.filteredOptions.length === 0) {
      var empty = document.createElement('li');
      empty.style.cssText = 'padding:8px 12px;color:#64748b;font-size:12px;text-align:center;';
      empty.textContent = 'No matches found';
      empty.setAttribute('role', 'option');
      empty.setAttribute('aria-disabled', 'true');
      this.listbox.appendChild(empty);
      return;
    }

    for (var i = 0; i < this.filteredOptions.length; i++) {
      var opt = this.filteredOptions[i];
      var li = document.createElement('li');
      li.id = this.id + '-option-' + i;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', opt.selected ? 'true' : 'false');
      li.setAttribute('data-index', i);
      li.textContent = opt.label;
      li.style.cssText =
        'padding:6px 12px;cursor:pointer;font-size:13px;color:#e2e8f0;' +
        'transition:background 0.1s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';

      if (opt.selected) {
        li.style.background = '#312e81';
        li.style.fontWeight = '500';
      }

      (function (idx) {
        li.addEventListener('mousedown', function (e) {
          e.preventDefault(); // Prevent blur from firing before selection
          self._selectOption(idx);
        });
        li.addEventListener('mouseenter', function () {
          self._setActive(idx);
        });
      })(i);

      this.listbox.appendChild(li);
    }
  };

  SearchableDropdown.prototype._moveActive = function (direction) {
    var newIndex = this.activeIndex + direction;
    if (newIndex < 0) newIndex = this.filteredOptions.length - 1;
    if (newIndex >= this.filteredOptions.length) newIndex = 0;
    this._setActive(newIndex);
  };

  SearchableDropdown.prototype._setActive = function (index) {
    // Remove previous active styling
    var items = this.listbox.querySelectorAll('[role="option"]');
    for (var i = 0; i < items.length; i++) {
      items[i].style.background = '';
      if (this.filteredOptions[i] && this.filteredOptions[i].selected) {
        items[i].style.background = '#312e81';
      }
    }

    this.activeIndex = index;
    if (index >= 0 && items[index]) {
      items[index].style.background = '#334155';
      items[index].scrollIntoView({ block: 'nearest' });
      this.input.setAttribute('aria-activedescendant', items[index].id);
    } else {
      this.input.removeAttribute('aria-activedescendant');
    }
  };

  SearchableDropdown.prototype._selectOption = function (index) {
    var opt = this.filteredOptions[index];
    if (!opt) return;

    // Update original select
    this.selectEl.value = opt.value;

    // Dispatch change event on the original select (for HTMX or other listeners)
    var evt = new Event('change', { bubbles: true });
    this.selectEl.dispatchEvent(evt);

    // Update internal state
    for (var i = 0; i < this.options.length; i++) {
      this.options[i].selected = (this.options[i].value === opt.value);
    }

    // Update input display
    this.input.value = opt.label;
    this.close();
  };

  SearchableDropdown.prototype.open = function () {
    if (this.isOpen) return;
    this.isOpen = true;
    this.listbox.style.display = 'block';
    this.input.setAttribute('aria-expanded', 'true');
    this._filter(this.input.value);
  };

  SearchableDropdown.prototype.close = function () {
    if (!this.isOpen) return;
    this.isOpen = false;
    this.listbox.style.display = 'none';
    this.input.setAttribute('aria-expanded', 'false');
    this.input.removeAttribute('aria-activedescendant');
    this.activeIndex = -1;
  };

  // Allow re-syncing if the select options change (e.g., HTMX swap)
  SearchableDropdown.prototype.refresh = function () {
    this._syncFromSelect();
  };

  // ─── Auto-init & Public API ───────────────────────────────────────────────

  function initAll() {
    var selects = document.querySelectorAll('select[data-searchable]');
    for (var i = 0; i < selects.length; i++) {
      if (!selects[i]._searchableDropdown) {
        var instance = new SearchableDropdown(selects[i]);
        selects[i]._searchableDropdown = instance;
        instances.push(instance);
      }
    }
  }

  // Init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }

  // Re-init after HTMX swaps (new selects may appear)
  document.addEventListener('htmx:afterSettle', initAll);

  // Public API
  window.SearchableDropdown = {
    init: function (selectEl, opts) {
      if (selectEl._searchableDropdown) {
        selectEl._searchableDropdown.refresh();
        return selectEl._searchableDropdown;
      }
      var instance = new SearchableDropdown(selectEl, opts);
      selectEl._searchableDropdown = instance;
      instances.push(instance);
      return instance;
    },
    initAll: initAll,
    refreshAll: function () {
      for (var i = 0; i < instances.length; i++) {
        instances[i].refresh();
      }
    }
  };
})();
