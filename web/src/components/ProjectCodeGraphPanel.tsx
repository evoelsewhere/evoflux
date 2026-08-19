import { searchProjectCodeGraph } from '@/api/client'
import type { CodingProject, WorkspaceFileInfo } from '@/api/types'
import { useProjectCodeGraph } from '@/hooks/useProjectCodeGraph'
import { queryKeys } from '@/queries/keys'
import { CodeGraphOverview } from './CodeGraphOverview'
import { RepoGraphModal } from './RepoGraphModal'

export interface ProjectCodeGraphPanelProps {
  project: CodingProject
  onFileSelect?: (file: WorkspaceFileInfo | null) => void
}

export function ProjectCodeGraphPanel({ project, onFileSelect }: ProjectCodeGraphPanelProps) {
  const { repos, summary, statusQuery, reindex, reindexMutation, isBusy } =
    useProjectCodeGraph(project.id)

  return (
    <CodeGraphOverview
      scopeName={project.name}
      repositoryCount={project.workspaces.length}
      repos={repos}
      summary={summary}
      statusLoading={statusQuery.isLoading}
      statusError={statusQuery.isError}
      reindexError={reindexMutation.isError}
      isBusy={isBusy}
      onReindex={reindex}
      searchKey={(query) => queryKeys.projects.codeGraphSearch(project.id, query)}
      searchGraph={(query, signal) =>
        searchProjectCodeGraph(project.id, query, { limit: 40, signal })
      }
      renderExplorer={(open, onOpenChange) => (
        <RepoGraphModal
          open={open}
          onOpenChange={onOpenChange}
          project={project}
          onFileSelect={onFileSelect}
        />
      )}
      onFileSelect={onFileSelect}
    />
  )
}
