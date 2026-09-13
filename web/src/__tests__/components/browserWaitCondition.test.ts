import { describe, expect, it } from 'vitest'

import {
  browserFitOverride,
  browserScreenshotPoint,
  browserNavigationCommitted,
  browserDataStoreIdentifier,
  browserViewportLayout,
  browserViewportPlan,
  browserWaitConditionSatisfied,
  MIN_FIT_SCALE,
} from '@/components/BrowserViewer/useDirectBrowserTabs'

const baseExpected = {
  selector: '#result',
  state: 'visible',
  text: 'Saved',
  urlContains: '/settings',
  loadState: 'complete',
}

describe('direct browser wait conditions', () => {
  it('requires every requested browser condition', () => {
    expect(browserWaitConditionSatisfied({
      attached: true,
      visible: true,
      text: 'Settings Saved',
      url: 'https://example.com/settings',
      readyState: 'complete',
    }, baseExpected)).toBe(true)

    expect(browserWaitConditionSatisfied({
      attached: true,
      visible: false,
      text: 'Settings Saved',
      url: 'https://example.com/settings',
      readyState: 'complete',
    }, baseExpected)).toBe(false)
  })

  it('treats a detached element as hidden', () => {
    expect(browserWaitConditionSatisfied({ attached: false }, {
      selector: '.toast',
      state: 'hidden',
      text: '',
      urlContains: '',
      loadState: '',
    })).toBe(true)
  })
})

describe('direct browser responsive viewport layout', () => {
  it('uses the browser panel bounds when no override is active', () => {
    expect(browserViewportLayout({ x: 12.4, y: 30.6, width: 719.7, height: 600.2 }, null))
      .toEqual({ x: 12, y: 31, width: 720, height: 600, scale: 1 })
  })

  it('scales and centers a desktop viewport without letting it cover app chrome', () => {
    expect(browserViewportLayout(
      { x: 300, y: 100, width: 640, height: 700 },
      { width: 1280, height: 800 },
    )).toEqual({
      x: 300,
      y: 250,
      width: 640,
      height: 400,
      scale: 0.5,
    })
  })

  it('keeps a mobile viewport at native CSS size and centers it', () => {
    expect(browserViewportLayout(
      { x: 100, y: 50, width: 700, height: 900 },
      { width: 375, height: 812 },
    )).toEqual({
      x: 263,
      y: 94,
      width: 375,
      height: 812,
      scale: 1,
    })
  })

  it('maps scaled screenshot pixels back to CSS viewport coordinates', () => {
    expect(browserScreenshotPoint(
      { x: 320, y: 200 },
      { width: 640, height: 400 },
      { width: 1280, height: 800 },
    )).toEqual({ x: 640, y: 400 })
  })
})

describe('direct browser desktop fit', () => {
  it('lays a narrow panel out at the target width and fills it exactly', () => {
    const container = { x: 0, y: 0, width: 800, height: 600 }
    const override = browserFitOverride(container, 1280)
    expect(override).toEqual({ width: 1280, height: 960 })

    // The scaled view must cover the panel: a letterbox here would be the
    // dark bars the device-emulation path deliberately shows.
    const layout = browserViewportLayout(container, override)
    expect(layout.width).toBe(800)
    expect(layout.height).toBe(600)
    expect(layout.scale).toBeCloseTo(0.625, 5)
  })

  it('leaves a panel that is already wide enough at its native width', () => {
    expect(browserFitOverride({ width: 1400, height: 900 }, 1280)).toBeNull()
  })

  it('gives up rather than rendering text too small to read', () => {
    const width = Math.floor(1280 * MIN_FIT_SCALE) - 1
    expect(browserFitOverride({ width, height: 600 }, 1280)).toBeNull()
  })

  it('is off when no target width is configured', () => {
    expect(browserFitOverride({ width: 800, height: 600 }, null)).toBeNull()
  })
})

describe('direct browser viewport plan', () => {
  const container = { x: 0, y: 0, width: 800, height: 600 }

  it('applies the user zoom when nothing is scaling the view', () => {
    const plan = browserViewportPlan(container, null, null, 125)
    expect(plan.override).toBeNull()
    expect(plan.zoomFactor).toBeCloseTo(1.25, 5)
  })

  it('multiplies fit scale by the user zoom so the zoom control still works', () => {
    const plan = browserViewportPlan(container, null, 1280, 150)
    expect(plan.override).toEqual({ width: 1280, height: 960 })
    expect(plan.zoomFactor).toBeCloseTo(0.625 * 1.5, 5)
  })

  it("lets an agent's device viewport own the zoom, so the tested width is exact", () => {
    const plan = browserViewportPlan(container, { width: 1280, height: 800 }, 1280, 150)
    expect(plan.override).toEqual({ width: 1280, height: 800 })
    expect(plan.zoomFactor).toBeCloseTo(plan.layout.scale, 5)
  })
})

describe('direct browser document navigation', () => {
  it('does not accept the old complete document when navigating to the same URL', () => {
    expect(browserNavigationCommitted(
      {
        url: 'https://example.com',
        readyState: 'complete',
        documentId: 'old-document',
      },
      'https://example.com',
      'https://example.com',
      'old-document',
    )).toBe(false)
  })

  it('accepts a new committed document and redirects', () => {
    expect(browserNavigationCommitted(
      {
        url: 'https://example.com/dashboard',
        readyState: 'interactive',
        documentId: 'new-document',
      },
      'https://example.com/login',
      'https://example.com',
      'old-document',
    )).toBe(true)
  })
})

describe('direct browser profile isolation', () => {
  it('derives stable distinct 16-byte data-store identifiers per session', () => {
    const first = browserDataStoreIdentifier('session-one')
    expect(first).toHaveLength(16)
    expect(browserDataStoreIdentifier('session-one')).toEqual(first)
    expect(browserDataStoreIdentifier('session-two')).not.toEqual(first)
    expect(first[6] & 0xf0).toBe(0x40)
    expect(first[8] & 0xc0).toBe(0x80)
  })
})
