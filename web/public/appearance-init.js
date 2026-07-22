// Pre-paint appearance application. Keep in sync with web/src/lib/appearance.ts.
(function () {
  try {
    var raw = localStorage.getItem('oa-appearance');
    if (!raw) return;
    var parsed = JSON.parse(raw);
    var root = document.documentElement;
    var ACCENTS = ['default', 'blue', 'green', 'orange', 'pink', 'purple', 'red'];
    var accent = ACCENTS.indexOf(parsed.accent) !== -1 ? parsed.accent : 'default';
    if (accent !== 'default') {
      var ref = 'var(--accent-' + accent + ')';
      root.style.setProperty('--focus-ring', ref);
      root.style.setProperty('--color-accent', ref);
    }

    var FONTS = ['inter', 'system', 'mono', 'geist', 'source-sans'];
    var font = FONTS.indexOf(parsed.fontFamily) !== -1 ? parsed.fontFamily : 'inter';
    root.setAttribute('data-font', font);

    var scale = [0.9, 1, 1.1, 1.2].indexOf(parsed.fontScale) !== -1 ? parsed.fontScale : 1;
    if (scale !== 1) {
      root.style.setProperty('font-size', (18 * scale) + 'px');
    }
  } catch (e) {
    // Fall back to default appearance (the canonical default in index.css).
  }
})();
