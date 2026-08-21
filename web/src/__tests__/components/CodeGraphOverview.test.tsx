import { act, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CODE_GRAPH_SEARCH_DEBOUNCE_MS,
  CodeGraphOverview,
} from '@/components/CodeGraphOverview'
import type { ProjectRepoStatus } from '@/api/types'

const repo: ProjectRepoStatus = {
  workspace_id: 'repo-1',
  path: '/workspace/repository',
  name: 'repository',
  indexed: true,
  files: 12,
  nodes: 120,
  edges: 240,
  indexing: false,
  index_phase: null,
  index_progress: null,
  index_message: null,
  index_error: null,
}

afterEach(() => {
  vi.useRealTimers()
})

describe('CodeGraphOverview', () => {
  it('uses panel container breakpoints and starts search without a long debounce', async () => {
    vi.useFakeTimers()
    const searchGraph = vi.fn().mockResolvedValue({ results: [] })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <CodeGraphOverview
          scopeName="repository"
          repositoryCount={1}
          repos={[repo]}
          summary={{ indexed: 1, failed: 0, files: 12, symbols: 120, relations: 240, coverage: 1 }}
          statusLoading={false}
          statusError={false}
          reindexError={false}
          isBusy={false}
          onReindex={vi.fn()}
          searchKey={(query) => ['graph-search', query]}
          searchGraph={searchGraph}
          renderExplorer={() => null}
        />
      </QueryClientProvider>,
    )

    expect(container.firstElementChild).toHaveClass('@container/code-graph')
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'symbol' },
    })
    expect(searchGraph).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(CODE_GRAPH_SEARCH_DEBOUNCE_MS)
    })

    expect(searchGraph).toHaveBeenCalledWith('symbol', expect.any(AbortSignal))
  })
})
