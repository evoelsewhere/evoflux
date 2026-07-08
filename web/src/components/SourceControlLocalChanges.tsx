import { useState } from 'react'
import { DiffEditor, useMonaco } from '@monaco-editor/react'
import { useMonacoTheme, languageForExt } from '@/hooks/useMonacoTheme'
import { useToastStore } from '@/stores/useToastStore'
import { useGitChangesQuery, useGitDiffViewQuery, useGitDiscardMutation } from '@/queries/useGitQuery'
import { SourceControlFileList } from './SourceControlFileList'

function extOf(path: string): string {
  const i = path.lastIndexOf('.')
  return i >= 0 ? path.slice(i + 1).toLowerCase() : 'txt'
}

export interface SourceControlLocalChangesProps {
  workspace: string
  onFileOpenInEditor?: (path: string) => void
}

export function SourceControlLocalChanges({
  workspace,
  onFileOpenInEditor,
}: SourceControlLocalChangesProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const changesQuery = useGitChangesQuery(workspace)
  const diffViewQuery = useGitDiffViewQuery(workspace, selectedPath, !!selectedPath)
  const discardMutation = useGitDiscardMutation(workspace)
  const monaco = useMonaco()
  const theme = useMonacoTheme(monaco)

  const files = changesQuery.data?.files ?? []
  const selectedFile = files.find((f) => f.path === selectedPath)
  const isConflicted = selectedFile?.status === 'unmerged'

  const diffText = diffViewQuery.data?.diff ?? ''
  const parts = parseDiff(diffText)

  const handleDiscard = (path: string) => {
    discardMutation.mutate([path], {
      onSuccess: () => {
        useToastStore.getState().push({ tone: 'success', title: 'Changes discarded' })
      },
      onError: (err) => {
        useToastStore.getState().push({
          tone: 'error',
          title: 'Discard failed',
          description: err instanceof Error ? err.message : undefined,
        })
      },
    })
    if (selectedPath === path) setSelectedPath(null)
  }

  return (
    <div className="flex min-h-0 flex-1">
      {/* File list — left pane */}
      <div className="w-64 shrink-0 overflow-auto border-r border-(--color-border)">
        <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
          <span className="text-xs font-medium text-(--color-text-muted)">
            {changesQuery.isLoading ? 'Loading…' : `${files.length} changed`}
          </span>
        </div>
        <div className="p-1">
          <SourceControlFileList
            files={files}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
            showStageControls={false}
            showDiscard
            onDiscard={handleDiscard}
          />
        </div>
      </div>

      {/* Diff viewer — right pane */}
      <div className="min-w-0 flex-1">
        {!selectedPath ? (
          <div className="flex h-full items-center justify-center text-xs text-(--color-text-subtle)">
            Select a file to view diff
          </div>
        ) : isConflicted && onFileOpenInEditor ? (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <p className="text-xs text-red-400">This file has merge conflicts</p>
            <button
              type="button"
              onClick={() => onFileOpenInEditor(selectedPath)}
              className="rounded bg-(--bg-key) px-3 py-1.5 text-xs text-(--color-text) hover:bg-(--bg-key)/70"
            >
              Open in editor to resolve
            </button>
          </div>
        ) : diffViewQuery.isLoading ? (
          <div className="flex h-full items-center justify-center text-xs text-(--color-text-subtle)">
            Loading diff…
          </div>
        ) : diffViewQuery.isError ? (
          <div className="flex h-full items-center justify-center text-xs text-(--color-error)">
            Failed to load diff
          </div>
        ) : (
          <div className="h-full">
            <DiffEditor
              key={selectedPath}
              original={parts.original}
              modified={parts.modified}
              language={languageForExt(extOf(selectedPath))}
              theme={theme}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 12,
                lineHeight: 20,
                scrollBeyondLastLine: false,
                wordWrap: 'on',
                renderOverviewRuler: false,
                overviewRulerBorder: false,
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function parseDiff(diff: string): { original: string; modified: string } {
  if (!diff) return { original: '', modified: '' }
  const original: string[] = []
  const modified: string[] = []
  for (const line of diff.split('\n')) {
    if (line.startsWith('@@')) continue
    if (line.startsWith('---') || line.startsWith('+++')) continue
    if (line.startsWith('-')) {
      original.push(line.slice(1))
    } else if (line.startsWith('+')) {
      modified.push(line.slice(1))
    } else {
      original.push(line.startsWith(' ') ? line.slice(1) : line)
      modified.push(line.startsWith(' ') ? line.slice(1) : line)
    }
  }
  return { original: original.join('\n'), modified: modified.join('\n') }
}
