import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function EasdTechnicalText({
  text,
  className,
}: {
  text: string
  className?: string
}) {
  const segments = text.split(/(`[^`\n]+`)/g)
  return (
    <span className={className}>
      {segments.map((segment, index) => {
        if (segment.startsWith('`') && segment.endsWith('`')) {
          return (
            <code key={`${segment}-${index}`} className="rounded bg-(--color-accent)/9 px-1 py-0.5 font-mono text-[0.92em] font-medium text-(--color-accent)">
              {segment.slice(1, -1)}
            </code>
          )
        }
        return <span key={`${segment}-${index}`}>{segment}</span>
      })}
    </span>
  )
}

function commandTokens(command: string): ReactNode[] {
  let tokenIndex = 0
  let executableSeen = false
  return command.split(/(\s+)/).map((token) => {
    const key = `${token}-${tokenIndex++}`
    if (!token.trim()) return <span key={key}>{token}</span>
    if (!executableSeen) {
      executableSeen = true
      return <span key={key} className="font-semibold text-(--color-accent)">{token}</span>
    }
    if (token.startsWith('-')) {
      return <span key={key} className="text-(--color-warning)">{token}</span>
    }
    if (token.includes('/') || token.includes('.') || token.includes(':')) {
      return <span key={key} className="text-(--color-success)">{token}</span>
    }
    return <span key={key} className="text-(--color-text-2)">{token}</span>
  })
}

export function EasdCommandBlock({
  commands,
  className,
  prompt = '$',
}: {
  commands: string[]
  className?: string
  prompt?: '$' | '!'
}) {
  return (
    <pre className={cn('overflow-x-auto whitespace-pre-wrap rounded-lg border border-(--color-border) bg-(--bg-key)/55 p-2.5 font-mono text-[9px] leading-4', className)}>
      {commands.map((command, index) => (
        <code key={`${command}-${index}`} className="block">
          <span aria-hidden="true" className="select-none text-(--color-text-subtle)">{prompt} </span>
          {commandTokens(command)}
        </code>
      ))}
    </pre>
  )
}
