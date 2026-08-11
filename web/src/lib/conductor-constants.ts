export const CONDUCTOR_ACTION = {
  APPROVE: 'approve',
  CONNECT: 'connect',
  DISCONNECT: 'disconnect',
  PULL: 'pull',
  SAVE: 'save',
  SYNC: 'sync',
} as const

export type ConductorAction = (typeof CONDUCTOR_ACTION)[keyof typeof CONDUCTOR_ACTION]

export const CONDUCTOR_ENFORCEMENT = {
  ENFORCE: 'enforce',
  REPORT: 'report',
} as const

export const CONDUCTOR_RESOURCE_KIND = {
  AGENT: 'agent',
  PLUGIN: 'plugin',
  SKILL: 'skill',
} as const

export const CONDUCTOR_RESOURCE_STATE = {
  APPLIED: 'applied',
  DECLINED: 'declined',
  ERROR: 'error',
  INCOMPATIBLE: 'incompatible',
  IN_SYNC: 'in_sync',
  OWNERSHIP_CONFLICT: 'ownership_conflict',
  PENDING: 'pending',
  PROJECT_SCOPE_MISMATCH: 'project_scope_mismatch',
  REMOVED: 'removed',
  STAGED: 'staged',
  TRUST_PENDING: 'trust_pending',
  UPDATE_PENDING: 'update_pending',
} as const

export type ConductorResourceState =
  (typeof CONDUCTOR_RESOURCE_STATE)[keyof typeof CONDUCTOR_RESOURCE_STATE]

export const CONDUCTOR_RESOURCE_STATE_LABEL: Record<ConductorResourceState, string> = {
  [CONDUCTOR_RESOURCE_STATE.APPLIED]: 'Applied',
  [CONDUCTOR_RESOURCE_STATE.DECLINED]: 'Declined',
  [CONDUCTOR_RESOURCE_STATE.ERROR]: 'Sync error',
  [CONDUCTOR_RESOURCE_STATE.INCOMPATIBLE]: 'Incompatible',
  [CONDUCTOR_RESOURCE_STATE.IN_SYNC]: 'In sync',
  [CONDUCTOR_RESOURCE_STATE.OWNERSHIP_CONFLICT]: 'Ownership conflict',
  [CONDUCTOR_RESOURCE_STATE.PENDING]: 'Pending',
  [CONDUCTOR_RESOURCE_STATE.PROJECT_SCOPE_MISMATCH]: 'Project mismatch',
  [CONDUCTOR_RESOURCE_STATE.REMOVED]: 'Removed',
  [CONDUCTOR_RESOURCE_STATE.STAGED]: 'Staged',
  [CONDUCTOR_RESOURCE_STATE.TRUST_PENDING]: 'Trust review',
  [CONDUCTOR_RESOURCE_STATE.UPDATE_PENDING]: 'Update available',
}

export const CONDUCTOR_VERSION_GAP_LABEL = {
  major: 'Major update',
  minor: 'Feature update',
  patch: 'Patch update',
  prerelease: 'Pre-release update',
  unknown: 'Version update',
} as const
