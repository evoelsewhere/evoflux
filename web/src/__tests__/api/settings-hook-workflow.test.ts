import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deleteSettingsHookWorkflowContent,
  getSettingsHookWorkflowContent,
  saveSettingsHookWorkflowContent,
} from '@/api/client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Settings hook workflow content API', () => {
  it('sends the opaque workflow id and Markdown to the fixed content endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ path: './settings-workflows/0123456789abcdef0123456789abcdef.md' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    const result = await saveSettingsHookWorkflowContent(
      '0123456789abcdef0123456789abcdef',
      '# My workflow\n\nUse the project skill.',
    )

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      '/api/settings/hooks/workflows/0123456789abcdef0123456789abcdef/content',
    )
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: '# My workflow\n\nUse the project skill.' }),
    })
    expect(result.path).toBe('./settings-workflows/0123456789abcdef0123456789abcdef.md')
  })

  it('surfaces the API validation message when Markdown cannot be saved', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'workflow content exceeds the 64 KiB limit' }),
      { status: 422, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(saveSettingsHookWorkflowContent('0'.repeat(32), 'x'.repeat(70_000)))
      .rejects.toThrow('workflow content exceeds the 64 KiB limit')
  })

  it('reads and deletes content through the same fixed workflow identity', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        path: './settings-workflows/0123456789abcdef0123456789abcdef.md',
        content: '# Guide\n\nDo the work.',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ deleted: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const content = await getSettingsHookWorkflowContent('0123456789abcdef0123456789abcdef')
    const deleted = await deleteSettingsHookWorkflowContent('0123456789abcdef0123456789abcdef')

    expect(content.content).toBe('# Guide\n\nDo the work.')
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      '/api/settings/hooks/workflows/0123456789abcdef0123456789abcdef/content',
    )
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'DELETE' })
    expect(deleted.deleted).toBe(true)
  })
})
