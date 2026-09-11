/**
 * The file explorer's right-click menu, shared by Work and Code mode trees.
 *
 * Covers what the trees rely on: the menu only offers what the tree can
 * actually do, "Attach as context" reaches the chat composer, copy actions
 * hit the clipboard with the right shape of path, and destructive actions
 * ask first.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/hooks/use-platform', () => ({
  getPlatform: () => ({ isTauri: true, os: 'windows', isMacOverlay: false }),
  usePlatform: () => ({ isTauri: true, os: 'windows', isMacOverlay: false }),
}))

vi.mock('@/queries/useWorkspaceOpenersQuery', () => ({
  useWorkspaceOpenersQuery: () => ({
    data: [{ id: 'vscode', name: 'VS Code', kind: 'editor', icon_data_url: null }],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}))

const { openWith } = vi.hoisted(() => ({ openWith: vi.fn(async () => undefined) }))
vi.mock('@/api/tauri-workspace', () => ({ tauriOpenWorkspaceWith: openWith }))

import {
  FileExplorerContextMenu,
  type FileExplorerMenuActions,
} from '@/components/FileExplorerContextMenu'

const entry = { path: 'src/app.py', name: 'app.py', isDirectory: false }
const folder = { path: 'src', name: 'src', isDirectory: true }

function stubClipboard() {
  const spy = vi.fn(async () => undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: spy },
    configurable: true,
  })
  return spy
}

function renderMenu(actions: FileExplorerMenuActions, target = entry) {
  return render(
    <FileExplorerContextMenu entry={target} actions={actions}>
      <button type="button">{target.name}</button>
    </FileExplorerContextMenu>,
  )
}

async function openMenu(name: string) {
  fireEvent.contextMenu(screen.getByRole('button', { name }))
  await waitFor(() => expect(screen.getByRole('menu')).toBeTruthy())
}

async function clickItem(name: RegExp) {
  const item = await screen.findByRole('menuitem', { name })
  await act(async () => {
    fireEvent.click(item)
  })
}

beforeEach(() => {
  openWith.mockClear()
})

describe('FileExplorerContextMenu', () => {
  it('offers only the actions the tree provided', async () => {
    renderMenu({ root: 'C:\\repo' })
    await openMenu('app.py')

    expect(screen.getByRole('menuitem', { name: /attach as context/i })).toBeTruthy()
    // No preview/rename/delete handlers were passed, so those stay hidden
    // rather than showing as dead entries.
    expect(screen.queryByRole('menuitem', { name: /preview/i })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: /rename/i })).toBeNull()
    expect(screen.queryByRole('menuitem', { name: /delete/i })).toBeNull()
  })

  it('sends the path to the chat composer as an @-mention', async () => {
    const inserted: string[] = []
    const listener = (event: Event) => {
      inserted.push((event as CustomEvent<{ text?: string }>).detail?.text ?? '')
    }
    window.addEventListener('evoflux:composer-insert', listener)

    renderMenu({})
    await openMenu('app.py')
    await clickItem(/attach as context/i)

    window.removeEventListener('evoflux:composer-insert', listener)
    expect(inserted).toEqual(['@src/app.py'])
  })

  it('copies the workspace-absolute path with native separators', async () => {
    const clipboard = stubClipboard()

    renderMenu({ root: 'C:\\repo' })
    await openMenu('app.py')
    await clickItem(/^copy$/i)
    await clickItem(/absolute path/i)

    await waitFor(() => expect(clipboard).toHaveBeenCalledWith('C:\\repo\\src\\app.py'))
  })

  it('opens one entry — not the workspace root — in a detected editor', async () => {
    renderMenu({ root: '/repo' })
    await openMenu('app.py')
    await clickItem(/^open in$/i)
    await clickItem(/vs code/i)

    await waitFor(() => expect(openWith).toHaveBeenCalledWith('/repo', 'vscode', 'src/app.py'))
  })

  it('confirms before deleting, and says the folder goes with its contents', async () => {
    const onDelete = vi.fn(async () => undefined)

    renderMenu({ root: '/repo', onDelete }, folder)
    await openMenu('src')
    await clickItem(/delete/i)

    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toMatch(/everything inside it/i)
    expect(onDelete).not.toHaveBeenCalled()

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    })
    expect(onDelete).toHaveBeenCalledWith(folder)
  })

  it('renames through a prompt prefilled with the current name', async () => {
    const onRename = vi.fn(async () => undefined)

    renderMenu({ onRename })
    await openMenu('app.py')
    await clickItem(/rename/i)

    const input = await screen.findByRole('textbox')
    expect((input as HTMLInputElement).value).toBe('app.py')
    fireEvent.change(input, { target: { value: 'main.py' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })

    await waitFor(() => expect(onRename).toHaveBeenCalledWith(entry, 'main.py'))
  })
})
