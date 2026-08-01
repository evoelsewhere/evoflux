/**
 * Settings dirty registry — editor pages register a live dirty predicate so
 * SettingsScreen / navigate / close can confirm before discarding drafts.
 *
 * Pages remount on path change (`SettingsContent` key), so without a guard
 * sidebar clicks and Escape silently wipe unsaved agent/skill/MCP/sandbox
 * edits. Explicit "Leave without saving" passes `force: true`.
 */
import { useEffect, useRef } from 'react'

type DirtyChecker = () => boolean

const checkers = new Set<DirtyChecker>()

export function registerSettingsDirty(checker: DirtyChecker): () => void {
  checkers.add(checker)
  return () => {
    checkers.delete(checker)
  }
}

export function isSettingsDirty(): boolean {
  for (const check of checkers) {
    if (check()) return true
  }
  return false
}

/** Returns true when navigation/close may proceed. */
export function confirmDiscardSettingsDraft(): boolean {
  if (!isSettingsDirty()) return true
  return window.confirm('You have unsaved settings changes. Discard them?')
}

/** Register a boolean dirty flag for the lifetime of the calling component. */
export function useRegisterSettingsDirty(dirty: boolean): void {
  const dirtyRef = useRef(dirty)
  useEffect(() => {
    dirtyRef.current = dirty
  }, [dirty])
  useEffect(() => registerSettingsDirty(() => dirtyRef.current), [])
}
