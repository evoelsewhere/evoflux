import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  skillRecordingVideoUrl,
  uploadSkillRecordingVideo,
} from '@/api/client/skillRecordings'

afterEach(() => {
  vi.unstubAllGlobals()
  delete window.__OAD_API_BASE_URL__
})

describe('skill recording video API', () => {
  it('uploads the WebM blob to the recording artifact route', async () => {
    const uploadResult = {
      recording_id: 'recording-id',
      artifact_id: 'video',
      media_type: 'video/webm',
      byte_length: 12,
      expires_at: '2026-10-08T04:00:00+00:00',
    }
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(uploadResult), { status: 201 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    window.__OAD_API_BASE_URL__ = 'http://127.0.0.1:4082/api'
    const video = new Blob(['synthetic webm'], { type: 'video/webm' })

    await expect(uploadSkillRecordingVideo('recording-id', video)).resolves.toEqual(uploadResult)

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:4082/api/skill-recordings/recording-id/video',
      expect.objectContaining({
        method: 'PUT',
        headers: { 'Content-Type': 'video/webm' },
        body: video,
      }),
    )
    expect(skillRecordingVideoUrl('recording-id')).toBe(
      'http://127.0.0.1:4082/api/skill-recordings/recording-id/video',
    )
  })
})
