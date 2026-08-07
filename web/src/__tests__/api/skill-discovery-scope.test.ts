import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  deleteSkill,
  getRegistry,
  getSkill,
  listSkillFiles,
  resetSkillSettings,
  updateSkill,
  updateSkillSettings,
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
  it('sends every workspace as a repeated query parameter with the runtime mode', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)

    await listSkillFiles({
      workspaces: ['/repo/api', '/repo/web', '/repo/api'],
      mode: 'coding',
    })
    await getRegistry({ workspaces: ['/repo/api', '/repo/web'], mode: 'coding' })

    expect(requestedUrl(fetchMock).pathname).toBe('/api/skills')
    expect(requestedUrl(fetchMock).searchParams.getAll('workspace')).toEqual([
      '/repo/api',
      '/repo/web',
    ])
    expect(requestedUrl(fetchMock).searchParams.get('mode')).toBe('coding')
    expect(requestedUrl(fetchMock, 1).pathname).toBe('/api/agents/registry')
    expect(requestedUrl(fetchMock, 1).searchParams.getAll('workspace')).toEqual([
      '/repo/api',
      '/repo/web',
    ])
  })

  it('preserves scope for detail, update, and delete operations', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)
    const scope = { workspaces: ['/repo/app'], mode: 'work' as const }

    await getSkill('shared/skill', scope)
    await updateSkill('shared/skill', 'content', [], [], scope)
    await deleteSkill('shared/skill', scope)

    for (let call = 0; call < 3; call += 1) {
      const url = requestedUrl(fetchMock, call)
      expect(url.pathname).toBe('/api/skills/shared%2Fskill')
      expect(url.searchParams.getAll('workspace')).toEqual(['/repo/app'])
      expect(url.searchParams.get('mode')).toBe('work')
    }
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'PUT' })
    expect(fetchMock.mock.calls[2]?.[1]).toMatchObject({ method: 'DELETE' })
  })

  it('updates and resets runtime settings with collision-safe identity and scope', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => okJson())
    vi.stubGlobal('fetch', fetchMock)
    const scope = { workspaces: ['/repo/app'], mode: 'coding' as const }

    await updateSkillSettings(
      'nested/settings',
      {
        settings_id: 'workspace:/repo/app:shared/skill',
        modes: ['coding'],
        allow_implicit_invocation: false,
        user_invocable: true,
      },
      scope,
    )
    await resetSkillSettings('nested/settings', 'workspace:/repo/app:shared/skill', scope)

    const patchUrl = requestedUrl(fetchMock)
    expect(patchUrl.pathname).toBe('/api/skills/nested%2Fsettings')
    expect(patchUrl.searchParams.getAll('workspace')).toEqual(['/repo/app'])
    expect(patchUrl.searchParams.get('mode')).toBe('coding')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({
        settings_id: 'workspace:/repo/app:shared/skill',
        modes: ['coding'],
        allow_implicit_invocation: false,
        user_invocable: true,
      }),
    })

    const resetUrl = requestedUrl(fetchMock, 1)
    expect(resetUrl.pathname).toBe('/api/skills/nested%2Fsettings')
    expect(resetUrl.searchParams.get('settings_id')).toBe('workspace:/repo/app:shared/skill')
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'DELETE' })
  })

  it('keeps workspace and mode in scoped cache keys while retaining prefix keys', () => {
    expect(queryKeys.skillFiles.list(['/repo/a', '/repo/b'], 'coding')).toEqual([
      'skillFiles',
      'list',
      ['/repo/a', '/repo/b'],
      'coding',
    ])
    expect(queryKeys.skillFiles.detail('review', ['/repo/a'], 'work')).toEqual([
      'skillFiles',
      'detail',
      'review',
      ['/repo/a'],
      'work',
    ])
    expect(queryKeys.agentFiles.registry()).toEqual(['agentFiles', 'registry'])
  })
})
