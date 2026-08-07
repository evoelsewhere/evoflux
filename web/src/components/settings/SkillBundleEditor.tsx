import { useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import {
  Braces,
  File,
  FileCode2,
  FileText,
  FolderOpen,
  Plus,
  Trash2,
  Upload,
} from 'lucide-react'

import type { SkillBundleDraftFile } from '@/components/settings/skillBundle'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

interface SkillBundleEditorProps {
  skillContent: string
  onSkillContentChange: (content: string) => void
  files: SkillBundleDraftFile[]
  onFilesChange: (files: SkillBundleDraftFile[]) => void
  readOnly?: boolean
  disabled?: boolean
  invalid?: boolean
}

const TEXT_EXTENSIONS = new Set([
  'css',
  'csv',
  'html',
  'js',
  'json',
  'jsx',
  'md',
  'py',
  'sh',
  'svg',
  'toml',
  'ts',
  'tsx',
  'txt',
  'xml',
  'yaml',
  'yml',
])

function uniqueDocumentPath(files: SkillBundleDraftFile[]): string {
  const paths = new Set(files.map((file) => file.path))
  let index = 1
  while (paths.has(`references/document-${index}.md`)) index += 1
  return `references/document-${index}.md`
}

function isTextFile(file: globalThis.File): boolean {
  if (file.type.startsWith('text/')) return true
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  return TEXT_EXTENSIONS.has(extension)
}

function fileIcon(path: string) {
  if (path.endsWith('.md') || path.endsWith('.txt')) return FileText
  if (path.startsWith('scripts/')) return FileCode2
  if (path.endsWith('.json') || path.endsWith('.yaml') || path.endsWith('.yml')) return Braces
  return File
}

export function SkillBundleEditor({
  skillContent,
  onSkillContentChange,
  files,
  onFilesChange,
  readOnly = false,
  disabled = false,
  invalid = false,
}: SkillBundleEditorProps) {
  const [selectedPath, setSelectedPath] = useState('SKILL.md')
  const uploadRef = useRef<HTMLInputElement>(null)
  const selected = files.find((file) => file.path === selectedPath)

  const addDocument = () => {
    const path = uniqueDocumentPath(files)
    onFilesChange([
      ...files,
      {
        path,
        content: '# Supporting document\n\nAdd reference material here.\n',
        encoding: 'utf-8',
        size: 0,
        mediaType: 'text/markdown',
        editable: true,
      },
    ])
    setSelectedPath(path)
  }

  const uploadFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const picked = [...(event.target.files ?? [])]
    if (picked.length === 0) return
    const existing = new Set(files.map((file) => file.path))
    const additions: SkillBundleDraftFile[] = []
    for (const file of picked) {
      let path = file.name
      let suffix = 2
      while (existing.has(path)) {
        const dot = file.name.lastIndexOf('.')
        path =
          dot > 0
            ? `${file.name.slice(0, dot)}-${suffix}${file.name.slice(dot)}`
            : `${file.name}-${suffix}`
        suffix += 1
      }
      existing.add(path)
      if (isTextFile(file)) {
        additions.push({
          path,
          content: await file.text(),
          encoding: 'utf-8',
          size: file.size,
          mediaType: file.type || 'text/plain',
          editable: true,
        })
      } else {
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result))
          reader.onerror = () => reject(reader.error)
          reader.readAsDataURL(file)
        })
        additions.push({
          path,
          content: dataUrl.split(',', 2)[1] ?? '',
          encoding: 'base64',
          size: file.size,
          mediaType: file.type || 'application/octet-stream',
          editable: false,
        })
      }
    }
    onFilesChange([...files, ...additions])
    setSelectedPath(additions[0]?.path ?? 'SKILL.md')
    event.target.value = ''
  }

  const updateSelected = (patch: Partial<SkillBundleDraftFile>) => {
    if (!selected) return
    const next = files.map((file) => (file.path === selected.path ? { ...file, ...patch } : file))
    onFilesChange(next)
    if (patch.path) setSelectedPath(patch.path)
  }

  const removeSelected = () => {
    if (!selected) return
    onFilesChange(files.filter((file) => file.path !== selected.path))
    setSelectedPath('SKILL.md')
  }

  return (
    <div className="overflow-hidden rounded-[12px] border border-(--color-border) bg-(--bg-page)">
      <div className="grid min-h-125 grid-cols-[minmax(220px,0.34fr)_minmax(0,1fr)] max-md:grid-cols-1">
        <aside className="border-r border-(--color-border) bg-(--bg-key)/45 p-2 max-md:border-r-0 max-md:border-b">
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <div>
              <p className="text-xs font-semibold text-(--color-text)">Bundle files</p>
              <p className="text-[11px] text-(--color-text-muted)">{files.length + 1} files</p>
            </div>
            {!readOnly && (
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  title="Add document"
                  onClick={addDocument}
                  disabled={disabled}
                >
                  <Plus aria-hidden="true" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  title="Upload files"
                  onClick={() => uploadRef.current?.click()}
                  disabled={disabled}
                >
                  <Upload aria-hidden="true" />
                </Button>
                <input
                  ref={uploadRef}
                  className="hidden"
                  type="file"
                  multiple
                  onChange={(event) => void uploadFiles(event)}
                />
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => setSelectedPath('SKILL.md')}
            className={cn(
              'flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left text-xs transition-colors',
              selectedPath === 'SKILL.md'
                ? 'bg-(--bg-key) font-medium text-(--color-text)'
                : 'text-(--color-text-muted) hover:bg-(--bg-hover)',
            )}
          >
            <SparkleFile />
            <span className="truncate">SKILL.md</span>
            <span
              className="ml-auto text-xs font-semibold text-(--color-accent)"
              title="Required file"
              aria-label="required"
            >
              *
            </span>
          </button>

          <div className="mt-1 space-y-0.5">
            {files.map((file) => {
              const Icon = fileIcon(file.path)
              return (
                <button
                  key={file.path}
                  type="button"
                  onClick={() => setSelectedPath(file.path)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-[8px] px-2.5 py-2 text-left text-xs transition-colors',
                    selectedPath === file.path
                      ? 'bg-(--bg-key) font-medium text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-hover)',
                  )}
                >
                  <Icon className="size-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate">{file.path}</span>
                </button>
              )
            })}
          </div>
        </aside>

        <section className="flex min-w-0 flex-col">
          {selectedPath === 'SKILL.md' ? (
            <>
              <div className="flex h-11 items-center gap-2 border-b border-(--color-border) px-3">
                <SparkleFile />
                <span className="text-xs font-medium">SKILL.md</span>
              </div>
              <Textarea
                aria-label="SKILL.md source"
                value={skillContent}
                onChange={(event) => onSkillContentChange(event.target.value)}
                disabled={disabled}
                readOnly={readOnly}
                spellCheck={false}
                aria-invalid={invalid || undefined}
                className="min-h-112 flex-1 resize-none rounded-none border-0 bg-transparent font-mono text-[13px] leading-relaxed focus-visible:ring-0"
              />
            </>
          ) : selected ? (
            <>
              <div className="flex min-h-11 items-center gap-2 border-b border-(--color-border) px-3">
                <FolderOpen className="size-3.5 text-(--color-text-muted)" aria-hidden="true" />
                <Input
                  aria-label="Bundle file path"
                  value={selected.path}
                  onChange={(event) => updateSelected({ path: event.target.value })}
                  readOnly={readOnly || selected.content === null}
                  disabled={disabled}
                  className="h-7 border-0 bg-transparent px-1 font-mono text-xs focus-visible:ring-0"
                />
                {!readOnly && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    title="Remove file"
                    onClick={removeSelected}
                    disabled={disabled}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                )}
              </div>
              {selected.content !== null && selected.encoding === 'utf-8' ? (
                <Textarea
                  aria-label={`Contents of ${selected.path}`}
                  value={selected.content}
                  onChange={(event) =>
                    updateSelected({
                      content: event.target.value,
                      size: new Blob([event.target.value]).size,
                    })
                  }
                  disabled={disabled}
                  readOnly={readOnly}
                  spellCheck={false}
                  className="min-h-112 flex-1 resize-none rounded-none border-0 bg-transparent font-mono text-[13px] leading-relaxed focus-visible:ring-0"
                />
              ) : (
                <div className="flex min-h-112 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
                  <File className="size-8 text-(--color-text-subtle)" aria-hidden="true" />
                  <p className="text-sm font-medium text-(--color-text)">
                    {selected.encoding === 'utf-8'
                      ? 'Text preview unavailable'
                      : 'Binary asset'}
                  </p>
                  <p className="max-w-sm text-xs text-(--color-text-muted)">
                    {selected.mediaType} · {formatBytes(selected.size)}. It remains part of the
                    bundle and will stay unchanged when you save.
                  </p>
                </div>
              )}
            </>
          ) : null}
        </section>
      </div>
    </div>
  )
}

function SparkleFile() {
  return <FileCode2 className="size-3.5 shrink-0 text-(--color-accent)" aria-hidden="true" />
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
