import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { RepoGraphSpatial } from '@/components/RepoGraphSpatial'
import type { SpatialGraphData, SpatialNode } from '@/components/repoGraphSpatialData'
import type { CodeGraphNode, ProjectRepoStatus } from '@/api/types'

vi.mock('@/hooks/useThemePreference', () => ({
  useThemePreference: () => ({ resolved: 'light' }),
}))

vi.stubGlobal(
  'ResizeObserver',
  class ResizeObserver {
    observe() {}
    disconnect() {}
  },
)

const repoStatus: ProjectRepoStatus = {
  workspace_id: 'repo-1',
  path: '/workspace/repo',
  name: 'repo',
  indexed: true,
  files: 10,
  nodes: 100,
  edges: 200,
  indexing: false,
  index_phase: null,
  index_progress: null,
  index_message: null,
  index_error: null,
}

const symbol: CodeGraphNode = {
  id: 'symbol-1',
  workspace_id: 'repo-1',
  kind: 'function',
  name: 'run',
  qualified_name: 'run',
  file_path: 'src/main.ts',
  language: 'typescript',
  line_start: 1,
  line_end: 2,
  signature: 'function run()',
  docstring: null,
}

function spatialNode(
  id: string,
  data: ProjectRepoStatus | CodeGraphNode,
  repo: boolean,
): SpatialNode {
  return {
    id,
    workspaceId: 'repo-1',
    kind: repo ? 'repo' : 'function',
    label: repo ? 'repo' : 'run',
    fullLabel: repo ? '/workspace/repo' : 'run',
    radius: 4,
    baseColor: '#000',
    textColor: '#000',
    glowColor: '#000',
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    mass: 1,
    repo,
    data,
  }
}

describe('RepoGraphSpatial', () => {
  it('labels the bounded constellation as a sample of authoritative totals', () => {
    const repoNode = spatialNode('repo:repo-1', repoStatus, true)
    const symbolNode = spatialNode('symbol-1', symbol, false)
    const data: SpatialGraphData = {
      repos: [repoStatus],
      nodes: [repoNode, symbolNode],
      edges: [],
      nodeById: new Map([[repoNode.id, repoNode], [symbolNode.id, symbolNode]]),
      edgesByNodeId: new Map(),
      totalNodeCount: 100,
      totalEdgeCount: 200,
      nodeLimitPerRepo: 1,
      edgeLimitPerRepo: 1,
    }

    render(
      <RepoGraphSpatial
        data={data}
        searchQuery=""
        selectedId={null}
        onSelect={() => undefined}
        hiddenRepoIds={new Set()}
      />,
    )

    expect(screen.getByText('1/100 symbols')).toBeInTheDocument()
    expect(screen.getByText('0/200 relations')).toBeInTheDocument()
    expect(screen.getByText('sampled')).toBeInTheDocument()
  })
})
