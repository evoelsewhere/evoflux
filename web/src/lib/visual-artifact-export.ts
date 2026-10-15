/** Prefer MP4 only when the active browser reports a compatible recorder. */
export function getSupportedExportMimeType(
  MediaRecorderCtor: typeof MediaRecorder | null | undefined,
): string | null {
  if (!MediaRecorderCtor) return null
  return [
    'video/mp4;codecs=avc1.42E01E',
    'video/mp4',
    'video/webm;codecs=vp9',
    'video/webm',
  ].find((mimeType) => MediaRecorderCtor.isTypeSupported(mimeType)) ?? null
}
