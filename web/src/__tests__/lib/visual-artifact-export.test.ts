import { describe, expect, it, vi } from 'vitest'
import { getSupportedExportMimeType } from '@/lib/visual-artifact-export'

describe('motion export MIME selection', () => {
  it('chooses MP4 only when supported and otherwise reports WebM', () => {
    const mp4 = { isTypeSupported: vi.fn((mime: string) => mime === 'video/mp4') } as unknown as typeof MediaRecorder
    expect(getSupportedExportMimeType(mp4)).toBe('video/mp4')
    const webm = { isTypeSupported: vi.fn((mime: string) => mime === 'video/webm;codecs=vp9') } as unknown as typeof MediaRecorder
    expect(getSupportedExportMimeType(webm)).toBe('video/webm;codecs=vp9')
    expect(getSupportedExportMimeType(undefined)).toBeNull()
  })
})
