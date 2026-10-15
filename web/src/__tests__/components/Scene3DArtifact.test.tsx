import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Scene3DArtifact } from '@/components/visual-artifact/Scene3DArtifact'
import type { VisualArtifactPayload } from '@/api/types'

const artifact: VisualArtifactPayload = {
  artifactId: 'mechanism', kind: 'scene3d', title: 'Valve mechanism', summary: 'Rotating components',
  sourceHtml: null, durationMs: null, revision: 1,
  scene: { nodes: [{ id: 'housing', geometry: 'box', position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1], color: 'accent', label: 'Housing' }] },
  sources: [],
}

describe('3D artifact fallback', () => {
  it('shows an accessible static scene when WebGL cannot initialize', async () => {
    render(<Scene3DArtifact artifact={artifact} reducedMotion={false} resolvedTheme="dark" />)
    expect(await screen.findByText(/3D is unavailable/i)).toBeVisible()
    expect(screen.getByRole('img', { name: /static scene preview/i })).toBeVisible()
    expect(screen.getByText('Housing')).toBeVisible()
  })
})
