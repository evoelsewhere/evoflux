import { afterEach, describe, expect, it } from 'vitest'

import { withAmdDefineHidden } from '@/components/markdown/amdDefine'

const scope = globalThis as { define?: unknown }

describe('withAmdDefineHidden', () => {
  const original = scope.define
  afterEach(() => {
    scope.define = original
  })

  it('keeps define hidden until the last overlapping render finishes', async () => {
    const amdDefine = () => {}
    scope.define = amdDefine
    let releaseFirst!: () => void
    let releaseSecond!: () => void
    const first = withAmdDefineHidden(
      () => new Promise<void>((resolve) => { releaseFirst = resolve }),
    )
    const second = withAmdDefineHidden(
      () => new Promise<void>((resolve) => { releaseSecond = resolve }),
    )
    expect(scope.define).toBeUndefined()

    releaseFirst()
    await first
    expect(scope.define).toBeUndefined()

    releaseSecond()
    await second
    expect(scope.define).toBe(amdDefine)
  })

  it('restores define when the render fails', async () => {
    const amdDefine = () => {}
    scope.define = amdDefine
    await expect(
      withAmdDefineHidden(() => Promise.reject(new Error('boom'))),
    ).rejects.toThrow('boom')
    expect(scope.define).toBe(amdDefine)
  })
})
