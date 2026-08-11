export const CONDUCTOR_ACTION = {
  APPROVE: 'approve',
  CONNECT: 'connect',
  DISCONNECT: 'disconnect',
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
  ERROR: 'error',
  INCOMPATIBLE: 'incompatible',
  IN_SYNC: 'in_sync',
  OWNERSHIP_CONFLICT: 'ownership_conflict',
  TRUST_PENDING: 'trust_pending',
} as const
