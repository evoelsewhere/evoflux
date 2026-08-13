import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TodoItem } from '@/api/types'
import { InputBar } from '@/components/InputBar'

const unfinishedTodos: TodoItem[] = [
  {
    task_id: 'task-1',
    content: 'Finish the remaining work',
    status: 'in_progress',
    priority: 'high',
  },
  {
    task_id: 'task-2',
    content: 'Verify the result',
    status: 'pending',
    priority: 'medium',
  },
]

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

describe('InputBar todo progress', () => {
  it('shows unfinished progress without a loading spinner after the session ends', () => {
    render(<InputBar onSubmit={vi.fn()} todos={unfinishedTodos} isStreaming={false} />)

    const progress = screen.getByRole('button', { name: /Step 1 \/ 2/ })
    expect(progress.querySelector('.lucide-list-todo')).toBeInTheDocument()
    expect(progress.querySelector('.animate-spin')).not.toBeInTheDocument()
  })

  it('shows the loading spinner while the session is streaming', () => {
    render(<InputBar onSubmit={vi.fn()} todos={unfinishedTodos} isStreaming />)

    const progress = screen.getByRole('button', { name: /Step 1 \/ 2/ })
    expect(progress.querySelector('.lucide-loader-circle')).toHaveClass('animate-spin')
  })
})
