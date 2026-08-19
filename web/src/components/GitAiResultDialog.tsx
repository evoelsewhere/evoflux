import { Copy, Sparkles, X } from 'lucide-react'

import type { GitAIResponse } from '@/api/types'
import { useToastStore } from '@/stores/useToastStore'

export function GitAiResultDialog({
  result,
  onClose,
}: {
  result: GitAIResponse
  onClose: () => void
}) {
  const pushToast = useToastStore((state) => state.push)
  const content = [result.title, result.body, result.message].filter(Boolean).join('\n\n')
  const copy = async () => {
    await navigator.clipboard.writeText(content || result.summary)
    pushToast({ tone: 'success', title: 'Copied AI Git result' })
  }
  return (
    <div className="fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-3 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="AI Git result">
      <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-page) shadow-2xl">
        <header className="flex items-center gap-2 border-b border-(--color-border) px-4 py-3">
          <Sparkles size={15} className="text-(--color-accent)" />
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-(--color-text)">{result.summary}</h2>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-(--color-text-muted) hover:bg-(--bg-key)" aria-label="Close AI Git result"><X size={14} /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {result.title && <h3 className="text-sm font-semibold text-(--color-text)">{result.title}</h3>}
          {result.body && <p className="mt-3 whitespace-pre-wrap text-xs leading-5 text-(--color-text-2)">{result.body}</p>}
          {result.message && <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-(--color-border) bg-(--bg-card) p-3 font-mono text-xs leading-5 text-(--color-text-2)">{result.message}</pre>}
          {result.findings.length > 0 && <p className="mt-3 text-xs text-(--color-text-muted)">{result.findings.length} finding{result.findings.length === 1 ? '' : 's'} added to Problems.</p>}
        </div>
        <footer className="flex justify-end gap-2 border-t border-(--color-border) px-4 py-3">
          {content && <button type="button" onClick={() => { void copy() }} className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs text-(--color-text-muted) hover:bg-(--bg-key)"><Copy size={12} /> Copy</button>}
          <button type="button" onClick={onClose} className="rounded-lg bg-(--color-accent) px-3 py-2 text-xs font-medium text-(--color-text-on-accent)">Done</button>
        </footer>
      </div>
    </div>
  )
}
