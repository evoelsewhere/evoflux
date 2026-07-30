import { describe, expect, it } from 'vitest'

import { formatApprovalQuestion } from '@/utils/approvalQuestion'

describe('formatApprovalQuestion', () => {
  it('extracts text from structured content blocks', () => {
    expect(
      formatApprovalQuestion(
        'Approval required\n\n[{"type":"text","text":"Run the migration?"}]',
      ),
    ).toBe('Approval required\n\nRun the migration?')
  })

  it('joins multiple text blocks and decodes a streaming fragment', () => {
    expect(
      formatApprovalQuestion(
        '[{"text":"First"},{"type":"text","text":"Second"}]',
      ),
    ).toBe('First\n\nSecond')
    expect(
      formatApprovalQuestion('[{"text":"Line one\\nLine two'),
    ).toBe('Line one\nLine two')
  })

  it('supports string/object payloads and ignores non-text blocks', () => {
    expect(formatApprovalQuestion('"plain text"')).toBe('plain text')
    expect(formatApprovalQuestion('{"text":"object text"}')).toBe('object text')
    expect(
      formatApprovalQuestion(
        '[null,42,{"type":"image"},{"text":42},{"text":"kept"}]',
      ),
    ).toBe('kept')
    expect(formatApprovalQuestion('[{"type":"image"}]')).toBe(
      '[{"type":"image"}]',
    )
  })

  it('decodes supported JSON escapes in incomplete streamed content', () => {
    expect(
      formatApprovalQuestion(
        '[{"text":"a\\rb\\tc\\bd\\fe\\"f\\\\g\\/h\\u0041',
      ),
    ).toBe('a\rb\tc\bd\fe"f\\g/hA')
  })

  it('stops safely on incomplete and invalid escapes', () => {
    expect(formatApprovalQuestion('[{"text":"before\\')).toBe('before')
    expect(formatApprovalQuestion('[{"text":"before\\u12xy')).toBe('before')
    expect(formatApprovalQuestion('[{"text":"before\\qafter')).toBe('beforeafter')
  })

  it('preserves ordinary questions', () => {
    expect(formatApprovalQuestion('Continue?')).toBe('Continue?')
    expect(formatApprovalQuestion('Title\n\nnot structured')).toBe(
      'Title\n\nnot structured',
    )
  })
})
