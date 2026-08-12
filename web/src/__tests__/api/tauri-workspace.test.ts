import { describe, expect, it } from 'vitest'

import { decodeBase64Utf8 } from '@/api/tauri-workspace'

describe('decodeBase64Utf8', () => {
  it('decodes Vietnamese, CJK, and emoji as UTF-8', () => {
    expect(decodeBase64Utf8('VGnhur9uZyBWaeG7h3Qg4oCUIOS4reaWhyDwn5iA')).toBe(
      'Tiếng Việt — 中文 😀',
    )
  })

  it('preserves ASCII text', () => {
    expect(decodeBase64Utf8('SGVsbG8sIHdvcmxkIQ==')).toBe('Hello, world!')
  })
})
