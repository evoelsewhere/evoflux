/**
 * Tests for the tier resolution utility and TierBadge component.
 */
import { describe, it, expect, afterEach } from 'bun:test'
import { render, screen, cleanup } from '@testing-library/react'
import { TierBadge } from '@/components/TierBadge'
import { resolveMemberTier } from '@/utils/tier'

afterEach(cleanup)

// ── resolveMemberTier ────────────────────────────────────────────────────────

describe('resolveMemberTier', () => {
  it('returns null when todos is empty', () => {
    expect(resolveMemberTier([], 'exec#1')).toBeNull()
  })

  it('returns null when no tasks belong to agent', () => {
    const todos = [{ tier: 'complex', assigned_to: 'explorer#1', status: 'pending' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBeNull()
  })

  it('returns null when all tasks are completed', () => {
    const todos = [{ tier: 'complex', assigned_to: 'exec#1', status: 'completed' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBeNull()
  })

  it('returns null when all tasks are cancelled', () => {
    const todos = [{ tier: 'complex', assigned_to: 'exec#1', status: 'cancelled' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBeNull()
  })

  it('returns tier from pending task', () => {
    const todos = [{ tier: 'simple', assigned_to: 'exec#1', status: 'pending' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('simple')
  })

  it('returns tier from in_progress task', () => {
    const todos = [{ tier: 'multi_step', assigned_to: 'exec#1', status: 'in_progress' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('multi_step')
  })

  it('uses claimed_by when assigned_to is absent', () => {
    const todos = [{ tier: 'complex', claimed_by: 'exec#1', status: 'in_progress' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('complex')
  })

  it('picks the highest tier across multiple active tasks', () => {
    const todos = [
      { tier: 'trivial', assigned_to: 'exec#1', status: 'pending' },
      { tier: 'multi_step', assigned_to: 'exec#1', status: 'in_progress' },
      { tier: 'simple', assigned_to: 'exec#1', status: 'pending' },
    ]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('multi_step')
  })

  it('complex beats all other tiers', () => {
    const todos = [
      { tier: 'simple', assigned_to: 'exec#1', status: 'pending' },
      { tier: 'complex', assigned_to: 'exec#1', status: 'pending' },
    ]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('complex')
  })

  it('defaults to simple when tier field is absent', () => {
    const todos = [{ assigned_to: 'exec#1', status: 'pending' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('simple')
  })

  it('defaults to simple when tier is an unrecognised string', () => {
    const todos = [{ tier: 'unknown', assigned_to: 'exec#1', status: 'pending' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('simple')
  })

  it('assigned_to wins over claimed_by when both are set for different agents', () => {
    // Backend: assigned_to or claimed_by  →  assigned_to takes precedence
    const todos = [{ tier: 'complex', assigned_to: 'exec#1', claimed_by: 'other#1', status: 'pending' }]
    expect(resolveMemberTier(todos, 'exec#1')).toBe('complex')
    expect(resolveMemberTier(todos, 'other#1')).toBeNull()
  })
})

// ── TierBadge ────────────────────────────────────────────────────────────────

describe('TierBadge', () => {
  it('renders trivial label', () => {
    render(<TierBadge tier="trivial" />)
    expect(screen.getByText('trivial')).toBeTruthy()
  })

  it('renders simple label', () => {
    render(<TierBadge tier="simple" />)
    expect(screen.getByText('simple')).toBeTruthy()
  })

  it('renders multi-step label for multi_step tier', () => {
    render(<TierBadge tier="multi_step" />)
    expect(screen.getByText('multi-step')).toBeTruthy()
  })

  it('renders complex label', () => {
    render(<TierBadge tier="complex" />)
    expect(screen.getByText('complex')).toBeTruthy()
  })

  it('has an aria-label describing the tier', () => {
    render(<TierBadge tier="simple" />)
    expect(screen.getByLabelText('Tier: simple')).toBeTruthy()
  })

  it('forwards extra className', () => {
    render(<TierBadge tier="trivial" className="my-custom-class" />)
    expect(screen.getByText('trivial').className).toContain('my-custom-class')
  })
})
