import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { I18nProvider } from '@/i18n/I18nProvider'
import { translate, translateText } from '@/i18n/catalog'
import { getLocale, initLocale, resetLocaleForTests, setLocale } from '@/i18n/locale'
import en from '@/i18n/messages/en.json'
import ja from '@/i18n/messages/ja.json'
import vi from '@/i18n/messages/vi.json'
import { STORAGE_KEYS } from '@/lib/storage-keys'

describe('i18n catalogs', () => {
  it('ships complete Vietnamese and Japanese catalogs', () => {
    expect(Object.keys(vi)).toEqual(Object.keys(en))
    expect(Object.keys(ja)).toEqual(Object.keys(en))
    expect(Object.keys(en).length).toBeGreaterThan(2_500)
    for (const [key, value] of Object.entries(vi)) {
      expect(value.match(/\{\d+\}/g)?.sort() ?? []).toEqual(key.match(/\{\d+\}/g)?.sort() ?? [])
    }
    for (const [key, value] of Object.entries(ja)) {
      expect(value.match(/\{\d+\}/g)?.sort() ?? []).toEqual(key.match(/\{\d+\}/g)?.sort() ?? [])
    }
  })

  it('translates exact and interpolated messages', () => {
    expect(translateText('Try again', 'vi')).toBe('Thử lại')
    expect(translateText('Try again', 'ja')).toBe('再試行')
    expect(translate('Delete task "{0}"?', ['release'], 'vi')).toBe('Xóa tác vụ "release"?')
    expect(translate('Delete task "{0}"?', ['release'], 'ja')).toBe('タスク「release」を削除しますか?')
  })

  it('keeps developer vocabulary and code-like literals out of machine Vietnamese', () => {
    expect(vi.Agent).toBe('Agent')
    expect(vi.Branch).toBe('Branch')
    expect(vi.Commit).toBe('Commit')
    expect(vi.Pipeline).toBe('Pipeline')
    expect(vi['Pop stash']).toBe('Áp dụng và xóa stash')
    expect(vi['[role="menuitem"]']).toBe(en['[role="menuitem"]'])

    const awkwardMachineTerms = /(?:đại lý|cam kết|chi nhánh|đường ống|người mẫu|kho nhạc pop|hộp cát|giấc mơ|yêu cầu kéo|điều khiển từ xa|mã thông báo|sân khấu|trận đấu|phòng thu âm|đột quỵ)/iu
    expect(Object.values(vi).filter((message) => awkwardMachineTerms.test(message))).toEqual([])
  })
})

describe('locale preference', () => {
  beforeEach(() => {
    resetLocaleForTests()
  })

  it('persists the locale and synchronizes the document language', () => {
    setLocale('ja')

    expect(getLocale()).toBe('ja')
    expect(localStorage.getItem(STORAGE_KEYS.locale)).toBe('ja')
    expect(document.documentElement.lang).toBe('ja')

    resetLocaleForTests()
    expect(initLocale()).toBe('ja')
  })
})

describe('DOM localization bridge', () => {
  beforeEach(() => {
    resetLocaleForTests()
    setLocale('en')
  })

  it('updates legacy UI text and attributes while preserving user content', async () => {
    render(
      <I18nProvider>
        <div>
          <button type="button" aria-label="Try again">Try again</button>
          <p data-testid="user-content" data-i18n-ignore>Try again</p>
        </div>
      </I18nProvider>,
    )

    act(() => setLocale('vi'))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Thử lại' })).toHaveTextContent('Thử lại')
    })
    expect(screen.getByTestId('user-content')).toHaveTextContent('Try again')

    act(() => setLocale('ja'))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '再試行' })).toHaveTextContent('再試行')
    })

    act(() => setLocale('en'))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Try again' })).toHaveTextContent('Try again')
    })
  })
})
