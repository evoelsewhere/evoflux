import { afterEach, describe, expect, it } from 'vitest'

import {
  clearSessionDropTarget,
  clearSessionDragPayload,
  isSessionDrag,
  markSessionDropHandled,
  readSessionDropTarget,
  readSessionDropTargetFromElement,
  readSessionDragPayload,
  SESSION_DRAG_MIME,
  setSessionDropTarget,
  setSessionDragPayload,
  wasSessionDropHandled,
} from '@/components/shell/session-drag'

function dragEvent(dataTransfer: DataTransfer): React.DragEvent {
  return { dataTransfer } as React.DragEvent
}

function dataTransfer(options?: { rejectCustomType?: boolean }): DataTransfer {
  const values = new Map<string, string>()
  const types: string[] = []
  return {
    effectAllowed: 'uninitialized',
    types,
    setData(type: string, value: string) {
      if (options?.rejectCustomType && type === SESSION_DRAG_MIME) {
        throw new DOMException('Custom drag types are unavailable')
      }
      values.set(type, value)
      if (!types.includes(type)) types.push(type)
    },
    getData(type: string) {
      if (options?.rejectCustomType && type === SESSION_DRAG_MIME) {
        throw new DOMException('Custom drag types are unavailable')
      }
      return values.get(type) ?? ''
    },
  } as unknown as DataTransfer
}

afterEach(clearSessionDragPayload)

describe('session drag payload', () => {
  it('uses the custom MIME payload in browsers that expose it', () => {
    const transfer = dataTransfer()
    const event = dragEvent(transfer)

    setSessionDragPayload(event, 'session-1')
    clearSessionDragPayload()

    expect(isSessionDrag(event)).toBe(true)
    expect(readSessionDragPayload(event)).toBe('session-1')
    expect(transfer.effectAllowed).toBe('move')
  })

  it('keeps same-window session drops working when a desktop WebView rejects custom MIME', () => {
    const transfer = dataTransfer({ rejectCustomType: true })
    const event = dragEvent(transfer)

    expect(() => setSessionDragPayload(event, 'session-desktop')).not.toThrow()
    expect(transfer.types).toEqual(['text/plain'])
    expect(isSessionDrag(event)).toBe(true)
    expect(readSessionDragPayload(event)).toBe('session-desktop')
  })

  it('does not treat an unrelated text drop as a session after drag cleanup', () => {
    const transfer = dataTransfer({ rejectCustomType: true })
    const event = dragEvent(transfer)

    setSessionDragPayload(event, 'session-1')
    clearSessionDragPayload()

    expect(isSessionDrag(event)).toBe(false)
    expect(readSessionDragPayload(event)).toBeNull()
  })

  it('retains the last valid folder target for a dragend fallback', () => {
    const event = dragEvent(dataTransfer())
    setSessionDragPayload(event, 'session-1')

    setSessionDropTarget('folder-1')
    expect(readSessionDropTarget()).toBe('folder-1')
    expect(wasSessionDropHandled()).toBe(false)

    markSessionDropHandled()
    expect(wasSessionDropHandled()).toBe(true)
  })

  it('clears only the target being left and distinguishes Recent from no target', () => {
    const event = dragEvent(dataTransfer())
    setSessionDragPayload(event, 'session-1')

    setSessionDropTarget('folder-2')
    clearSessionDropTarget('folder-1')
    expect(readSessionDropTarget()).toBe('folder-2')

    clearSessionDropTarget('folder-2')
    expect(readSessionDropTarget()).toBeUndefined()

    setSessionDropTarget(null)
    expect(readSessionDropTarget()).toBeNull()
  })

  it('resolves the release target from descendants of a folder or Recent zone', () => {
    const folder = document.createElement('div')
    const folderChild = document.createElement('span')
    folder.setAttribute('data-session-folder-drop-zone', 'folder-1')
    folder.append(folderChild)

    const recent = document.createElement('div')
    const recentChild = document.createElement('span')
    recent.setAttribute('data-session-unfile-drop-zone', '')
    recent.append(recentChild)

    expect(readSessionDropTargetFromElement(folderChild)).toBe('folder-1')
    expect(readSessionDropTargetFromElement(recentChild)).toBeNull()
    expect(readSessionDropTargetFromElement(document.createElement('div'))).toBeUndefined()
    expect(readSessionDropTargetFromElement(null)).toBeUndefined()
  })
})
