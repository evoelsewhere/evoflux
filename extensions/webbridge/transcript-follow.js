/* Codex-style pinned transcript following for the WebBridge Side Panel. */

(() => {
  const BOTTOM_THRESHOLD = 48;
  const USER_DETACH_DELTA = 4;
  const FOLLOW_TIME_CONSTANT_MS = 52;

  function isEditableTarget(target) {
    return target instanceof Element
      && target.closest('input, textarea, [contenteditable="true"]') !== null;
  }

  function isUpwardKey(event) {
    return event.key === "ArrowUp"
      || event.key === "PageUp"
      || event.key === "Home"
      || (event.key === " " && event.shiftKey);
  }

  function nextScrollTop(current, target, elapsedMs) {
    if (target <= current) return target;
    const elapsed = Math.min(48, Math.max(8, elapsedMs));
    const progress = 1 - Math.exp(-elapsed / FOLLOW_TIME_CONSTANT_MS);
    const next = current + ((target - current) * progress);
    return target - next < 0.75 ? target : next;
  }

  class TranscriptFollowController {
    constructor(element, latestButton, options = {}) {
      this.element = element;
      this.latestButton = latestButton;
      this.bottomThreshold = options.bottomThreshold ?? BOTTOM_THRESHOLD;
      this.pinned = true;
      this.awaitingDeparture = false;
      this.followFrame = null;
      this.viewportFrame = null;
      this.lastTouchY = null;
      this.previousTimestamp = null;

      this.onScroll = () => {
        if (this.viewportFrame === null) {
          this.viewportFrame = requestAnimationFrame(() => this.updateFromViewport());
        }
      };
      this.onWheel = (event) => {
        if (event.deltaY < -USER_DETACH_DELTA) this.detach();
      };
      this.onTouchMove = (event) => {
        const y = event.touches[0]?.clientY;
        if (y == null) return;
        if (this.lastTouchY !== null && y > this.lastTouchY + USER_DETACH_DELTA) this.detach();
        this.lastTouchY = y;
      };
      this.clearTouch = () => { this.lastTouchY = null; };
      this.onKeyDown = (event) => {
        if (!isEditableTarget(event.target) && isUpwardKey(event)) this.detach();
      };
      this.onPointerDown = (event) => {
        if (event.target !== this.element) return;
        const rect = this.element.getBoundingClientRect();
        const scrollbarWidth = Math.max(12, this.element.offsetWidth - this.element.clientWidth);
        if (event.clientX >= rect.right - scrollbarWidth) this.detach();
      };

      element.addEventListener("scroll", this.onScroll, { passive: true });
      element.addEventListener("wheel", this.onWheel, { passive: true });
      element.addEventListener("touchmove", this.onTouchMove, { passive: true });
      element.addEventListener("touchend", this.clearTouch, { passive: true });
      element.addEventListener("touchcancel", this.clearTouch, { passive: true });
      element.addEventListener("keydown", this.onKeyDown);
      element.addEventListener("pointerdown", this.onPointerDown, { passive: true });
      latestButton.addEventListener("click", () => this.reset());
      this.render();
    }

    isAtBottom() {
      return this.element.scrollHeight - this.element.scrollTop - this.element.clientHeight <= this.bottomThreshold;
    }

    render() {
      this.latestButton.classList.toggle("visible", !this.pinned);
    }

    cancelFollow() {
      if (this.followFrame !== null) cancelAnimationFrame(this.followFrame);
      this.followFrame = null;
      this.previousTimestamp = null;
    }

    detach() {
      this.awaitingDeparture = this.isAtBottom();
      this.pinned = false;
      this.cancelFollow();
      this.render();
    }

    reset() {
      this.pinned = true;
      this.awaitingDeparture = false;
      this.cancelFollow();
      this.render();
      this.element.scrollTop = this.element.scrollHeight;
    }

    updateFromViewport() {
      this.viewportFrame = null;
      const atBottom = this.isAtBottom();
      if (!this.pinned && !atBottom) this.awaitingDeparture = false;
      if (!this.pinned && atBottom && !this.awaitingDeparture) this.pinned = true;
      this.render();
      if (this.pinned && !atBottom) this.follow();
    }

    follow() {
      if (!this.pinned || this.followFrame !== null) return;
      const tick = (timestamp) => {
        this.followFrame = null;
        if (!this.pinned) return;
        const target = Math.max(0, this.element.scrollHeight - this.element.clientHeight);
        const reduced = document.documentElement.dataset.motion === "reduced"
          || globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
        if (reduced || target <= this.element.scrollTop) {
          this.element.scrollTop = target;
          this.previousTimestamp = null;
          return;
        }
        const elapsed = this.previousTimestamp === null ? 16 : timestamp - this.previousTimestamp;
        this.previousTimestamp = timestamp;
        this.element.scrollTop = nextScrollTop(this.element.scrollTop, target, elapsed);
        if (Math.abs(target - this.element.scrollTop) > 0.5) {
          this.followFrame = requestAnimationFrame(tick);
        } else {
          this.previousTimestamp = null;
        }
      };
      this.followFrame = requestAnimationFrame(tick);
    }
  }

  globalThis.WebBridgeTranscriptFollow = {
    create: (options) => new TranscriptFollowController(options.element, options.latestButton, options),
    nextScrollTop,
  };
})();
