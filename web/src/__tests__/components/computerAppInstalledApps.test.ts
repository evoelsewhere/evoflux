import { describe, expect, it } from 'vitest'

import { normalizeExe } from '@/components/ComputerAppViewer/useInstalledApps'

describe('normalizeExe', () => {
  it('names the same Windows executable however it was written', () => {
    expect(normalizeExe('Notepad', true)).toBe('notepad.exe')
    expect(normalizeExe(' notepad.EXE ', true)).toBe('notepad.exe')
    expect(normalizeExe('C:\\Windows\\System32\\notepad.exe', true)).toBe('notepad.exe')
    expect(normalizeExe('ms-teams.exe', true)).toBe('ms-teams.exe')
  })

  it('keeps macOS executables without a suffix', () => {
    expect(normalizeExe('TextEdit', false)).toBe('textedit')
    expect(normalizeExe('/System/Applications/TextEdit.app/Contents/MacOS/TextEdit', false)).toBe('textedit')
    expect(normalizeExe('MSTeams', false)).toBe('msteams')
  })

  it('leaves an empty name empty', () => {
    expect(normalizeExe('   ', true)).toBe('')
    expect(normalizeExe('   ', false)).toBe('')
  })
})
