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

    var FONTS = ['inter', 'system', 'mono', 'geist', 'anthropic-sans'];
    var font = parsed.fontFamily === 'source-sans'
      ? 'anthropic-sans'
      : (FONTS.indexOf(parsed.fontFamily) !== -1 ? parsed.fontFamily : 'system');
    root.setAttribute('data-font', font);

    var SCALES = [0.9, 0.95, 1, 1.05, 1.1, 1.15, 1.2];
    var scale = typeof parsed.fontScale === 'number' ? parsed.fontScale : 1;
    if (SCALES.indexOf(scale) === -1) {
      var best = 1;
      var bestDelta = Infinity;
      for (var i = 0; i < SCALES.length; i++) {
        var delta = Math.abs(SCALES[i] - scale);
        if (delta < bestDelta) {
          best = SCALES[i];
          bestDelta = delta;
        }
      }
      scale = best;
    }
    if (scale !== 1) {
      root.style.setProperty('font-size', (16 * scale) + 'px');
    }

    var MOTIONS = ['reduced', 'subtle', 'standard', 'expressive', 'cinematic'];
    var motion = MOTIONS.indexOf(parsed.motionIntensity) !== -1 ? parsed.motionIntensity : 'standard';
    root.setAttribute('data-motion', motion);
    var motionScale =
      motion === 'reduced' ? '0'
        : motion === 'subtle' ? '0.7'
          : motion === 'standard' ? '1'
            : motion === 'expressive' ? '1.25'
              : '1.55';
    root.style.setProperty('--motion-user-scale', motionScale);
  } catch (e) {
    // Fall back to default appearance (the canonical default in index.css).
  }
})();
