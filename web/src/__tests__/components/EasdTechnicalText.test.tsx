import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EasdCommandBlock, EasdTechnicalText } from '@/components/easd/EasdTechnicalText'
import { EasdChatMessage } from '@/components/easd/EasdChatMessage'
import { parseEasdChatMessage } from '@/utils/easd-chat-message'

describe('EasdTechnicalText', () => {
  it('renders backtick spans as lightweight inline code', () => {
    render(<p><EasdTechnicalText text="Run `python -m pytest` against `tests/test_api.py`." /></p>)

    expect(screen.getByText('python -m pytest').tagName).toBe('CODE')
    expect(screen.getByText('tests/test_api.py')).toHaveClass('font-mono')
    expect(screen.queryByText(/`python/)).not.toBeInTheDocument()
  })

  it('distinguishes executable, flags, and path arguments', () => {
    render(<EasdCommandBlock commands={['python -m pytest tests/test_api.py']} />)

    expect(screen.getByText('python')).toHaveClass('text-(--color-accent)')
    expect(screen.getByText('-m')).toHaveClass('text-(--color-warning)')
    expect(screen.getByText('tests/test_api.py')).toHaveClass('text-(--color-success)')
  })

  it('labels EASD chat phases and hides full revision hashes', () => {
    const hash = 'a'.repeat(64)
    const runId = '06a8fa49-a1c8-7ffb-8000-5aa016dc8d25'
    const content = `$easd-plan\n\nPlan EASD run ${runId} from accepted spec hash ${hash}. Run python -m pytest tests/test_api.py, then call easd_submit_plan with run ID ${runId}.`
    expect(parseEasdChatMessage(content)?.body).not.toContain(hash)
    expect(parseEasdChatMessage(content)?.body).not.toContain(runId)

    render(<EasdChatMessage content={content} />)

    expect(screen.getByText('EASD · Plan')).toBeInTheDocument()
    expect(screen.getByText('$easd-plan')).toBeInTheDocument()
    expect(screen.queryByText(hash)).not.toBeInTheDocument()
    expect(screen.queryByText(runId)).not.toBeInTheDocument()
    expect(screen.getByText('python -m pytest tests/test_api.py')).toHaveClass('font-mono')
    expect(screen.getByText('easd_submit_plan')).toHaveClass('font-mono')
  })
})
