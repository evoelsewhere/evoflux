import { readFileSync } from 'node:fs'
import path from 'node:path'
import { runInThisContext } from 'node:vm'
import { beforeEach, describe, expect, it } from 'vitest'

const SOURCE = readFileSync(path.join(process.cwd(), 'public', 'appearance-init.js'), 'utf8')

describe('appearance pre-paint script', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-font')
  })

  it.each(['inter', 'system', 'mono', 'geist', 'source-sans'])('sets data-font for %s before paint', (fontFamily) => {
    localStorage.setItem('oa-appearance', JSON.stringify({ fontFamily }))

    runInThisContext(SOURCE)

    expect(document.documentElement).toHaveAttribute('data-font', fontFamily)
  })

  it('migrates an unknown font to Inter without losing the pre-paint attribute', () => {
    localStorage.setItem('oa-appearance', JSON.stringify({ fontFamily: 'brand-private' }))

    runInThisContext(SOURCE)

    expect(document.documentElement).toHaveAttribute('data-font', 'inter')
  })
})
