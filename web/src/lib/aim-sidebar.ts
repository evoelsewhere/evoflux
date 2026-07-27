import {
  BookOpen,
  LayoutDashboard,
  Waypoints,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { STORAGE_KEYS } from '@/lib/storage-keys'

export type AimFeature = 'overview' | 'kb' | 'traceability' | 'pipelines'

export const AIM_FEATURES: { key: AimFeature; label: string; Icon: LucideIcon }[] = [
  { key: 'overview', label: 'Overview', Icon: LayoutDashboard },
  { key: 'kb', label: 'Knowledge Base', Icon: BookOpen },
  { key: 'traceability', label: 'Traceability', Icon: Waypoints },
  { key: 'pipelines', label: 'Pipelines', Icon: Workflow },
]

const LAST_AIM_PROJECT_KEY = STORAGE_KEYS.lastAimProject

export function saveLastAimProject(projectId: string): void {
  try {
    localStorage.setItem(LAST_AIM_PROJECT_KEY, projectId)
  } catch {
    // Ignore storage failures.
  }
}

export function clearLastAimProject(): void {
  try {
    localStorage.removeItem(LAST_AIM_PROJECT_KEY)
  } catch {
    // Ignore storage failures.
  }
}

export function loadLastAimProject(): string | null {
  try {
    return localStorage.getItem(LAST_AIM_PROJECT_KEY)
  } catch {
    return null
  }
}
