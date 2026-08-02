import { describe, expect, it } from 'vitest'
import { endCompaction, startCompaction } from './blocks'

describe('compaction blocks', () => {
  it('represent lifecycle state without summary content', () => {
    const compacting = startCompaction([])
    expect(compacting).toHaveLength(1)
    expect(compacting[0]).toMatchObject({
      type: 'compaction',
      content: '',
      extra: { state: 'compacting' },
    })

    const compacted = endCompaction(compacting, false)
    expect(compacted[0]).toMatchObject({
      type: 'compaction',
      content: '',
      extra: { state: 'compacted' },
    })
  })
})
