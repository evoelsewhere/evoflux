import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  createSkill,
  deleteSkill,
  getRegistry,
  getSkill,
  listSkillFiles,
  setSkillEnabled,
  updateSkill,
} from '@/api/client'
import { queryKeys } from '@/queries/keys'

function okJson(): Response {
  return new Response('{}', {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestedUrl(fetchMock: ReturnType<typeof vi.fn>, call = 0): URL {
  return new URL(String(fetchMock.mock.calls[call]?.[0]), window.location.origin)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('skill discovery API scope', () => {
  it('sends every workspace as a repeated query parameter and never a mode', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)

    await listSkillFiles({ workspaces: ['/repo/api', '/repo/web', '/repo/api', ' '] })
    await getRegistry({ workspaces: ['/repo/api', '/repo/web'] })

    expect(requestedUrl(fetchMock).pathname).toBe('/api/skills')
    expect(requestedUrl(fetchMock).searchParams.getAll('workspace')).toEqual([
      '/repo/api',
      '/repo/web',
    ])
    expect(requestedUrl(fetchMock).searchParams.has('mode')).toBe(false)
    expect(requestedUrl(fetchMock, 1).pathname).toBe('/api/agents/registry')
    expect(requestedUrl(fetchMock, 1).searchParams.getAll('workspace')).toEqual([
      '/repo/api',
      '/repo/web',
    ])
    expect(requestedUrl(fetchMock, 1).searchParams.has('mode')).toBe(false)
  })

  it('omits the query string for an unscoped catalog', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)

    await listSkillFiles()

    expect(requestedUrl(fetchMock).pathname).toBe('/api/skills')
    expect(requestedUrl(fetchMock).search).toBe('')
  })

  it('preserves scope for detail, update, enable, and delete operations', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)
    const scope = { workspaces: ['/repo/app'] }

    await getSkill('code-review', scope)
    await updateSkill('code-review', 'content', [], ['old.md'], scope)
    await setSkillEnabled('code-review', false, scope)
    await deleteSkill('code-review', scope)

    for (let call = 0; call < 4; call += 1) {
      const url = requestedUrl(fetchMock, call)
      expect(url.pathname).toBe('/api/skills/code-review')
      expect(url.searchParams.getAll('workspace')).toEqual(['/repo/app'])
    }
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: 'PUT',
      body: JSON.stringify({ content: 'content', files: [], deleted_files: ['old.md'] }),
    })
    expect(fetchMock.mock.calls[2]?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ enabled: false }),
    })
    expect(fetchMock.mock.calls[3]?.[1]).toMatchObject({ method: 'DELETE' })
  })

  it('creates a skill with only name, content and files', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)

    await createSkill('pdf-tools', '---\nname: pdf-tools\n---\n')

    expect(requestedUrl(fetchMock).pathname).toBe('/api/skills')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ name: 'pdf-tools', content: '---\nname: pdf-tools\n---\n', files: [] }),
    })
  })

  it('keeps workspaces in scoped cache keys while retaining prefix keys', () => {
    expect(queryKeys.skillFiles.list(['/repo/a', '/repo/b'])).toEqual([
      'skillFiles',
      'list',
      ['/repo/a', '/repo/b'],
    ])
    expect(queryKeys.skillFiles.detail('review', ['/repo/a'])).toEqual([
      'skillFiles',
      'detail',
      'review',
      ['/repo/a'],
    ])
    expect(queryKeys.skillFiles.list()).toEqual(['skillFiles', 'list'])
    expect(queryKeys.agentFiles.registry()).toEqual(['agentFiles', 'registry'])
    expect(queryKeys.agentFiles.registry(['/repo/a'])).toEqual([
      'agentFiles',
      'registry',
      ['/repo/a'],
    ])
  })
})
