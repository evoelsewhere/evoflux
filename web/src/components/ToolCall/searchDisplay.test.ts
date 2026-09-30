import { describe, expect, it } from 'vitest'

import { getToolDisplay } from './display'

const call = (args: Record<string, unknown>) => JSON.stringify(args)

describe('getToolDisplay for search tools', () => {
  it('reads "Searched <pattern>" once grep is done and "Searching" while it runs', () => {
    const display = getToolDisplay('grep', call({ pattern: 'TODO', directory: 'src' }))
    expect(display.completedLabel).toBe('Searched')
    expect(display.headerTitle).toBe('TODO in src')
    expect(display.activityLabel).toBe('Searching TODO in src')
  })

  it('names the grep filters and output mode', () => {
    const display = getToolDisplay(
      'grep',
      call({ pattern: 'fetch', include: '*.ts', type: 'ts', output_mode: 'files_with_matches' }),
    )
    expect(display.headerTitle).toBe('fetch (*.ts, type ts, files)')
    expect(
      getToolDisplay('grep', call({ pattern: 'x', include: '*', output_mode: 'count' })).headerTitle,
    ).toBe('x (count)')
    expect(
      getToolDisplay('grep', call({ pattern: 'x', output_mode: 'content' })).headerTitle,
    ).toBe('x')
  })

  it('reads "Found <pattern>" once glob is done', () => {
    const display = getToolDisplay('glob', call({ pattern: '*.py', match: 'name' }))
    expect(display.completedLabel).toBe('Found')
    expect(display.headerTitle).toBe('*.py (by name)')
    expect(display.activityLabel).toBe('Finding *.py (by name)')
  })
})
