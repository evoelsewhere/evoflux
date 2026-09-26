import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AppPicker } from '@/components/ComputerAppViewer/AppPicker'
import type { InstalledApp } from '@/components/ComputerAppViewer/useInstalledApps'

const APPS: InstalledApp[] = [
  { exe: 'notepad.exe', name: 'Notepad', running: true, icon: null },
  { exe: 'excel.exe', name: 'Excel', running: false, icon: null },
]

function Picker({ initial = [] as string[] }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <AppPicker value={value} onChange={setValue} apps={APPS} placeholder="Any app" ariaLabel="Allowed apps" />
      <output data-testid="value">{value.join(',')}</output>
    </>
  )
}

function search(text: string) {
  const input = screen.getByLabelText('Search apps')
  fireEvent.change(input, { target: { value: text } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

describe('AppPicker', () => {
  it('adds with Enter and never takes an app back off the list', () => {
    render(<Picker />)
    fireEvent.click(screen.getByRole('combobox', { name: 'Allowed apps' }))

    search('note')
    expect(screen.getByTestId('value').textContent).toBe('notepad.exe')

    // The same search again: Notepad is on the list already and stays there.
    search('note')
    expect(screen.getByTestId('value').textContent).toBe('notepad.exe')

    // Enter with an empty search does nothing either.
    fireEvent.keyDown(screen.getByLabelText('Search apps'), { key: 'Enter' })
    expect(screen.getByTestId('value').textContent).toBe('notepad.exe')

    // A name no app matches is added as typed.
    search('keepass')
    expect(screen.getByTestId('value').textContent).toMatch(/^notepad\.exe,keepass/)
  })
})
