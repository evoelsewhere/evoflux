import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { SkillRuntimeControls } from '@/components/settings/SkillRuntimeControls'

function Harness({ disabled = false }: { disabled?: boolean }) {
  const [autoDiscoverable, setAutoDiscoverable] = useState(true)
  const [manualInvocation, setManualInvocation] = useState(true)

  return (
    <SkillRuntimeControls
      allowImplicitInvocation={autoDiscoverable}
      userInvocable={manualInvocation}
      onAllowImplicitInvocationChange={setAutoDiscoverable}
      onUserInvocableChange={setManualInvocation}
      disabled={disabled}
    />
  )
}

describe('SkillRuntimeControls', () => {
  it('explains and edits agent discovery independently from manual invocation', () => {
    render(<Harness />)

    const discovery = screen.getByRole('switch', { name: 'Auto-discovery' })
    const manual = screen.getByRole('switch', { name: 'Manual invocation' })
    expect(discovery).toBeChecked()
    expect(discovery).toHaveAccessibleDescription(/only the skill name and description/i)
    expect(manual).toBeChecked()
    expect(manual).toHaveAccessibleDescription(/\/skill:name.*\$skill-name/i)
    expect(screen.getByText('Auto-discoverable')).toBeVisible()
    expect(screen.getByText('Available')).toBeVisible()

    fireEvent.click(discovery)
    fireEvent.click(manual)

    expect(discovery).not.toBeChecked()
    expect(manual).not.toBeChecked()
    expect(screen.getByText('Hidden from catalog')).toBeVisible()
    expect(screen.getByText('Disabled')).toBeVisible()
  })

  it('can lock runtime controls without changing their explanatory content', () => {
    render(<Harness disabled />)

    expect(screen.getByRole('switch', { name: 'Auto-discovery' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(screen.getByRole('switch', { name: 'Manual invocation' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(screen.getByText(/configured agents may still load it/i)).toBeVisible()
  })
})
