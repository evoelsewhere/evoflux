import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

describe('NativeSelect', () => {
  it('uses the operating-system select appearance when requested', () => {
    const { container } = render(
      <NativeSelect platformNative aria-label="Language">
        <NativeSelectOption value="en">English</NativeSelectOption>
      </NativeSelect>,
    )

    expect(screen.getByRole('combobox', { name: 'Language' })).toHaveAttribute('data-platform-native', 'true')
    expect(container.querySelector('[data-slot="native-select-icon"]')).not.toBeInTheDocument()
  })

  it('keeps the styled select as the default for existing consumers', () => {
    const { container } = render(
      <NativeSelect aria-label="Filter">
        <NativeSelectOption value="all">All</NativeSelectOption>
      </NativeSelect>,
    )

    expect(screen.getByRole('combobox', { name: 'Filter' })).not.toHaveAttribute('data-platform-native')
    expect(container.querySelector('[data-slot="native-select-icon"]')).toBeInTheDocument()
  })
})
