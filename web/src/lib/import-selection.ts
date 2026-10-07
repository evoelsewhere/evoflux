import { IMPORT_ITEM_KIND_OPTIONS, type ImportItemKind } from '@/api/import'
import { STORAGE_KEYS } from '@/lib/storage-keys'

export const IMPORT_WELCOME_SELECTION_EVENT = 'oa:import-welcome-selection'

export function saveWelcomeImportKinds(kinds: readonly ImportItemKind[]): void {
  sessionStorage.setItem(STORAGE_KEYS.import.welcomeSelection, JSON.stringify(kinds))
  window.dispatchEvent(new Event(IMPORT_WELCOME_SELECTION_EVENT))
}

export function takeWelcomeImportKinds(): ImportItemKind[] | null {
  const raw = sessionStorage.getItem(STORAGE_KEYS.import.welcomeSelection)
  if (!raw) return null
  sessionStorage.removeItem(STORAGE_KEYS.import.welcomeSelection)

  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return null
    const validKinds = parsed.filter((kind): kind is ImportItemKind =>
      IMPORT_ITEM_KIND_OPTIONS.some((option) => option.kind === kind),
    )
    return validKinds.length ? [...new Set(validKinds)] : null
  } catch {
    return null
  }
}
