import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkspaceFileInfo } from '@/api/types'

const { mediaUrl } = vi.hoisted(() => ({
  mediaUrl: vi.fn((_sessionId: string, path: string) => `/media/${path}?_token=test-token`),
}))

vi.mock('@/api/client', () => ({
  workspaceMediaUrl: mediaUrl,
}))

import { WorkspaceHtmlPreview } from '@/components/workspace-html-preview'

function file(path: string, mime = 'text/html'): WorkspaceFileInfo {
  return {
    path,
    name: path.split('/').at(-1) ?? path,
    mime,
    size: 256,
    mtime: 1,
  }
}

function mockWorkspaceFiles(contents: Record<string, string>) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const match = /^\/media\/(.*?)\?_token=test-token/.exec(url)
    const path = match?.[1]
    const content = path ? contents[path] : undefined
    return {
      ok: content !== undefined,
      status: content === undefined ? 404 : 200,
      text: async () => content ?? '',
    } as Response
  }))
}

beforeEach(() => {
  mediaUrl.mockClear()
})

describe('WorkspaceHtmlPreview', () => {
  it('renders regular HTML with local styles and assets inside an inert iframe', async () => {
    const html = file('site/pages/index.html')
    mockWorkspaceFiles({
      'site/pages/index.html': `<!doctype html><html><head>
        <link rel="stylesheet" href="./styles/site.css">
      </head><body>
        <img src="../assets/hero.png" alt="Hero">
        <script>window.parent.document.body.textContent = 'unsafe'</script>
      </body></html>`,
      'site/pages/styles/site.css': '.hero{background-image:url("../fonts/texture.png")}',
    })

    render(<WorkspaceHtmlPreview sessionId="session-1" file={html} files={[html]} />)

    const frame = await screen.findByTitle('index.html preview')
    const srcDoc = frame.getAttribute('srcdoc') ?? ''
    expect(frame).toHaveAttribute('sandbox', '')
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(srcDoc).toContain("script-src 'none'")
    expect(srcDoc).toContain('/media/site/assets/hero.png?_token=test-token')
    expect(srcDoc).toContain('/media/site/pages/fonts/texture.png?_token=test-token')
    expect(srcDoc).not.toContain('rel="stylesheet"')
  })

  it('assembles slide HTML with manifest CSS, assets, and a fitted canvas', async () => {
    const html = file('pptx_remake/slide-01.html')
    const project = file('pptx_remake/project.json', 'application/json')
    const css = file('pptx_remake/slide-01.css', 'text/css')
    const asset = file('pptx_remake/assets/hero.png', 'image/png')
    mockWorkspaceFiles({
      'pptx_remake/slide-01.html': '<main data-slide-root class="relative"><img src="asset://hero"></main>',
      'pptx_remake/project.json': JSON.stringify({
        width: 1280,
        height: 720,
        slides: [{
          id: 'opening',
          html_path: 'slide-01.html',
          style_paths: ['slide-01.css'],
          assets: { hero: 'assets/hero.png' },
        }],
      }),
      'pptx_remake/slide-01.css': '[data-slide-root]{background-image:url(asset://hero)}',
    })

    render(
      <WorkspaceHtmlPreview
        sessionId="session-1"
        file={html}
        files={[project, css, html, asset]}
      />,
    )

    const frame = await screen.findByTitle('slide-01.html preview')
    const srcDoc = frame.getAttribute('srcdoc') ?? ''
    expect(frame).toHaveStyle({ width: '1280px', height: '720px' })
    expect(srcDoc).toContain('[data-slide-root]{background-image:url("/media/pptx_remake/assets/hero.png?_token=test-token")}')
    expect(srcDoc).toContain('src="/media/pptx_remake/assets/hero.png?_token=test-token"')
    expect(srcDoc).toContain('[data-slide-root]{width:1280px;height:720px;overflow:hidden}')
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
  })
})
