// Pre-paint theme application. Keep in sync with web/src/lib/theme.ts.
(function () {
  try {
    var stored = localStorage.getItem('oa-theme');
    var pref = stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system';
    var resolved = pref === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : pref;
    var root = document.documentElement;
    root.classList.toggle('dark', resolved === 'dark');
    root.classList.toggle('light', resolved === 'light');
  } catch (e) {
    // Fall back to light (the canonical default in index.css).
    document.documentElement.classList.add('light');
  }
})();
