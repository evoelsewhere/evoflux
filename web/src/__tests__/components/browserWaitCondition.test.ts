import { describe, expect, it } from 'vitest'

import { browserWaitConditionSatisfied } from '@/components/BrowserViewer/useDirectBrowserTabs'

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
