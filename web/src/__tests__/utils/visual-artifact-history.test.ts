import { describe, expect, it } from 'vitest'
import { parseTeamBlocks } from '@/utils/messages'
import type { MessageResponse } from '@/api/types'

const messages: MessageResponse[] = [
  {
    id: 'assistant-source', session_id: 's', role: 'assistant', content: '', reasoning_content: null,
    tool_calls: [{ id: 'call-data', function: { name: 'mcp_salesforce.query', arguments: '{"limit":3}' } }],
    tool_call_id: null, name: null, is_summary: false, is_hidden: false, extra: null,
    created_at: '2026-10-15T00:00:00Z', attachments: null,
  },
  {
    id: 'tool-source', session_id: 's', role: 'tool', content: '{"success":true,"rows":3}', reasoning_content: null,
    tool_calls: null, tool_call_id: 'call-data', name: 'mcp_salesforce.query', is_summary: false,
    is_hidden: false, extra: null, created_at: '2026-10-15T00:00:01Z', attachments: null,
  },
  {
    id: 'assistant-artifact', session_id: 's', role: 'assistant', content: '', reasoning_content: null,
    tool_calls: [{ id: 'call-artifact', function: { name: 'visual_artifact', arguments: JSON.stringify({
      artifact_id: 'pipeline', kind: 'dashboard', title: 'Pipeline', summary: 'Open opportunities',
      source_html: '<main>3 rows</main>', sources: [{ tool_call_id: 'call-data', query_summary: 'open opportunities' }],
    }) } }], tool_call_id: null, name: null, is_summary: false, is_hidden: false, extra: null,
    created_at: '2026-10-15T00:00:02Z', attachments: null,
  },
]

describe('rich artifact history', () => {
  it('replays the artifact with the actual successful source call arguments and result', () => {
    const artifact = parseTeamBlocks(messages).find((block) => block.type === 'visual_artifact')?.visualArtifact
    expect(artifact?.sources[0]).toMatchObject({
      verified: true, toolName: 'mcp_salesforce.query', querySummary: 'open opportunities',
      arguments: '{"limit":3}', result: '{"success":true,"rows":3}',
    })
  })

  it('updates the stable artifact id in place for later history revisions', () => {
    const later = { ...messages[2], id: 'assistant-artifact-2', tool_calls: [{
      id: 'call-artifact-2', function: { name: 'visual_artifact', arguments: JSON.stringify({
        artifact_id: 'pipeline', kind: 'dashboard', title: 'Pipeline v2', summary: 'Updated', source_html: '<main>4 rows</main>', sources: [],
      }) },
    }] }
    const artifacts = parseTeamBlocks([...messages, later]).filter((block) => block.type === 'visual_artifact')
    expect(artifacts).toHaveLength(1)
    expect(artifacts[0].visualArtifact).toMatchObject({ artifactId: 'pipeline', title: 'Pipeline v2', revision: 2 })
  })
})
