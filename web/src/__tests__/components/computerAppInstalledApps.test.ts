import { describe, expect, it } from 'vitest'

import { normalizeExe } from '@/components/ComputerAppViewer/useInstalledApps'

describe('normalizeExe', () => {
  it('names the same executable however it was written', () => {
    expect(normalizeExe('Notepad')).toBe('notepad.exe')
    expect(normalizeExe(' notepad.EXE ')).toBe('notepad.exe')
    expect(normalizeExe('C:\\Windows\\System32\\notepad.exe')).toBe('notepad.exe')
    expect(normalizeExe('ms-teams.exe')).toBe('ms-teams.exe')
  })

  it('leaves an empty name empty', () => {
    expect(normalizeExe('   ')).toBe('')
  })
})
