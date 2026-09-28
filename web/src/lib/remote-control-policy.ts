/** Whether the Remote Control policy warning was dismissed for good here. */
import { STORAGE_KEYS } from '@/lib/storage-keys'

export function isRemoteControlPolicyAcknowledged(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.remoteControl.policyAcknowledged) === '1'
  } catch {
    return false
  }
}

export function acknowledgeRemoteControlPolicy(): void {
  try {
    localStorage.setItem(STORAGE_KEYS.remoteControl.policyAcknowledged, '1')
  } catch {
    // Storage unavailable: the warning simply shows again next visit.
  }
}
