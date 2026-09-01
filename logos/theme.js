/**
 * NPFL App — Shared Theme Toggle
 * Persists theme preference across all sections via localStorage.
 * Loaded early in <head> to prevent flash of wrong theme.
 *
 * The app opens in LIGHT mode. It used to follow the OS
 * prefers-color-scheme instead, so anyone on a dark-themed machine got a dark
 * app they never asked for. Dark is now opt-in via the toggle only.
 *
 * The storage key is versioned because the old code persisted the
 * OS-derived choice on a visitor's very first paint, which made an automatic
 * guess indistinguishable from a deliberate click. Bumping the key retires
 * those guesses; only an explicit toggle writes to the new key.
 */
(function () {
    var STORAGE_KEY = 'npfl-theme-v2';
    var DEFAULT_THEME = 'light';

    function getPreferred() {
        return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
    }

    function applyTheme(theme, suppressTransition, persist) {
        // Suppress CSS transitions on initial load to avoid flash
        if (suppressTransition) {
            var style = document.createElement('style');
            style.id = '__theme-no-transition';
            style.textContent = '*, *::before, *::after { transition: none !important; }';
            document.head.appendChild(style);
        }

        document.documentElement.setAttribute('data-theme', theme);

        // Only a deliberate choice is remembered. Persisting the automatic
        // default here would mean the "nothing stored yet" branch could never
        // be reached again after a single page view.
        if (persist) {
            localStorage.setItem(STORAGE_KEY, theme);
        }

        // Sync all toggle button icons/labels
        var btns = document.querySelectorAll('.theme-toggle-btn');
        btns.forEach(function (btn) {
            var icon = btn.querySelector('i');
            var label = btn.querySelector('.theme-label');
            if (theme === 'dark') {
                if (icon) icon.className = 'fas fa-sun';
                if (label) label.textContent = 'Light';
                btn.setAttribute('title', 'Switch to light mode');
            } else {
                if (icon) icon.className = 'fas fa-moon';
                if (label) label.textContent = 'Dark';
                btn.setAttribute('title', 'Switch to dark mode');
            }
        });

        // Re-enable transitions after next paint (prevents initial flash)
        if (suppressTransition) {
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    var el = document.getElementById('__theme-no-transition');
                    if (el) el.parentNode.removeChild(el);
                });
            });
        }
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme') || DEFAULT_THEME;
        // persist: this one IS the user deliberately choosing.
        applyTheme(current === 'dark' ? 'light' : 'dark', false, true);
    }

    // Apply immediately (before CSS renders) to prevent flash of wrong theme
    applyTheme(getPreferred(), true, false);

    // Expose globally for any custom integrations
    window.npflToggleTheme = toggleTheme;
    window.npflApplyTheme = applyTheme;

    // After DOM ready: re-sync icons and wire up all toggle buttons
    document.addEventListener('DOMContentLoaded', function () {
        applyTheme(getPreferred(), false, false);
        document.querySelectorAll('.theme-toggle-btn').forEach(function (btn) {
            // Avoid double-binding if already wired
            if (!btn.dataset.themeWired) {
                btn.dataset.themeWired = '1';
                btn.addEventListener('click', toggleTheme);
            }
        });
    });
})();
