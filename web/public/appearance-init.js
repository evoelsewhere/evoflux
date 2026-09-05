// Pre-paint appearance application. Keep in sync with web/src/lib/appearance.ts.
(function () {
  try {
    var raw = localStorage.getItem('oa-appearance');
    if (!raw) return;
    var parsed = JSON.parse(raw);
    var root = document.documentElement;
    var ACCENTS = [
      'default',
      'clay', 'red', 'orange', 'amber', 'lime', 'green', 'teal',
      'cyan', 'blue', 'indigo', 'purple', 'pink', 'rose', 'slate',
      'custom'
    ];
    var accent = ACCENTS.indexOf(parsed.accent) !== -1 ? parsed.accent : 'default';
    if (accent === 'custom') {
      var hex = typeof parsed.accentCustom === 'string' ? parsed.accentCustom.trim() : '';
      if (/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(hex)) {
        if (hex.length === 4) {
          hex = '#' + hex[1] + hex[1] + hex[2] + hex[2] + hex[3] + hex[3];
        }
        root.style.setProperty('--focus-ring', hex);
        root.style.setProperty('--color-accent', hex);
        // Same label-colour rule as accentContrast() in lib/appearance.ts.
        var chan = function (pair) {
          var v = parseInt(pair, 16) / 255;
          return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        };
        var lum = 0.2126 * chan(hex.slice(1, 3))
          + 0.7152 * chan(hex.slice(3, 5))
          + 0.0722 * chan(hex.slice(5, 7));
        var onDark = (lum + 0.05) / (0.0184 + 0.05);
        var onWhite = (1.05) / (lum + 0.05);
        root.style.setProperty('--color-text-on-accent', onDark >= onWhite ? '#211A16' : '#FFFFFF');
      }
    } else if (accent !== 'default') {
      var ref = 'var(--ui-accent-' + accent + ')';
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
