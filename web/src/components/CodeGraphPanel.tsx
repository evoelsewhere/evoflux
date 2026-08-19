import { searchCodeGraph } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'
import { useWorkspaceCodeGraph } from '@/hooks/useWorkspaceCodeGraph'
import { queryKeys } from '@/queries/keys'
import { CodeGraphOverview } from './CodeGraphOverview'
import { RepoGraphModal } from './RepoGraphModal'

export function CodeGraphPanel({
  workspace,
  onFileSelect,
}: {
  workspace: string
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
}) {
  const { repos, summary, statusQuery, reindex, reindexMutation, isBusy } =
    useWorkspaceCodeGraph(workspace)
  const scopeName = workspace.split(/[\\/]/).pop() || workspace

  return (
    <CodeGraphOverview
      scopeName={scopeName}
      repositoryCount={1}
      repos={repos}
      summary={summary}
      statusLoading={statusQuery.isLoading}
      statusError={statusQuery.isError}
      reindexError={reindexMutation.isError}
      isBusy={isBusy}
      onReindex={reindex}
      searchKey={(query) => queryKeys.codeGraph.query(workspace, query)}
      searchGraph={async (query, signal) => {
        const response = await searchCodeGraph(workspace, query, { limit: 20, signal })
        return {
          results: response.nodes.map((node) => ({ path: workspace, node })),
        }
      }}
      renderExplorer={(open, onOpenChange) => (
        <RepoGraphModal
          open={open}
          onOpenChange={onOpenChange}
          workspace={workspace}
          onFileSelect={onFileSelect}
        />
      )}
      onFileSelect={onFileSelect}
    />
  )
}
