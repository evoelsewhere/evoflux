import { describe, expect, it } from 'vitest'

import { parseVisualArtifactBridgeMessage, parseVisualArtifactMessage } from '@/lib/visual-artifact-bridge'

const validArtifact = {
  type: 'visual_artifact', agent: 'assistant', tool_call_id: 'call-2',
  artifact_id: 'budget', kind: 'dashboard', title: 'Budget', summary: 'Trip spend',
  source_html: '<main>Budget</main>', scene: null, sources: [], duration_ms: null, is_final: true,
}

describe('visual artifact payload validation', () => {
  it('converts a valid backend payload to the stable frontend shape', () => {
    expect(parseVisualArtifactMessage(validArtifact)).toMatchObject({ artifactId: 'budget', kind: 'dashboard', revision: 1 })
  })

  it('rejects unknown kinds and source HTML above the UTF-8 byte limit', () => {
    expect(parseVisualArtifactMessage({ ...validArtifact, kind: 'video' })).toBeNull()
    expect(parseVisualArtifactMessage({ ...validArtifact, source_html: 'é'.repeat(100_001) })).toBeNull()
  })

  it('accepts only bounded bridge messages', () => {
    expect(parseVisualArtifactBridgeMessage({ type: 'send_prompt', prompt: 'Refresh dashboard' })).toEqual({ type: 'send_prompt', prompt: 'Refresh dashboard' })
    expect(parseVisualArtifactBridgeMessage({ type: 'send_prompt', prompt: 'x'.repeat(10_001) })).toBeNull()
    expect(parseVisualArtifactBridgeMessage({ type: 'resize', height: 1_000_000 })).toBeNull()
  })
})
