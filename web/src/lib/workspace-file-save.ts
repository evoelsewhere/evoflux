import { getPlatform } from '@/hooks/use-platform'

/**
 * Write a copy of a workspace file to a location the user picks.
 *
 * Desktop opens the OS save dialog and the native side streams the bytes to
 * disk, so nothing passes through the browser's download machinery and the
 * desktop token never leaves the app process.
 *
 * In a browser the bytes are fetched first and saved from a blob URL: the
 * `download` attribute is ignored on a cross-origin href, and the API can be
 * served from a different origin than the app, which would otherwise navigate
 * to the file (losing the filename) instead of saving it.
 */
export async function saveWorkspaceFileFromUrl(url: string, filename: string): Promise<void> {
  if (getPlatform().isTauri) {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('save_workspace_file', { request: { url, filename } })
    return
  }

  try {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const objectUrl = URL.createObjectURL(await response.blob())
    clickDownloadAnchor(objectUrl, filename)
    URL.revokeObjectURL(objectUrl)
  } catch {
    // Last resort: let the browser handle the URL directly. It may open the
    // file instead of saving it, which still beats doing nothing.
    clickDownloadAnchor(url, filename)
  }
}

function clickDownloadAnchor(href: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}
