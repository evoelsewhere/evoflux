import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invoke } from '@tauri-apps/api/core'

import { getPlatform } from '@/hooks/use-platform'

import { computerAppSupported } from './computerAppBridge'

/** The macOS permissions Computer App Control needs, as the desktop reports them. */
export interface ComputerAppPermissions {
  /** False everywhere but macOS, where nothing has to be granted. */
  required: boolean
  accessibility: boolean
  screen_recording: boolean
}

export type ComputerAppPermission = 'accessibility' | 'screen_recording'

const PERMISSIONS_KEY = ['computer-app', 'permissions'] as const

/** Whether this desktop asks the user for permissions at all (macOS). */
export function computerAppNeedsPermissions(): boolean {
  return computerAppSupported() && getPlatform().os === 'macos'
}

/**
 * Which permissions EvoFlux has. The switches live in System Settings, so
 * while one is still off this checks again every couple of seconds (and
 * whenever EvoFlux regains focus) to notice the user turning it on.
 */
export function useComputerAppPermissions() {
  return useQuery({
    queryKey: PERMISSIONS_KEY,
    queryFn: () => invoke<ComputerAppPermissions>('app_computer_permissions'),
    enabled: computerAppNeedsPermissions(),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const data = query.state.data
      return data && (!data.accessibility || !data.screen_recording) ? 2_000 : false
    },
  })
}

/** Ask macOS for a permission and open its pane in System Settings. */
export function useRequestComputerAppPermission() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (kind: ComputerAppPermission) =>
      invoke<ComputerAppPermissions>('app_computer_request_permission', { kind }),
    onSuccess: (permissions) => queryClient.setQueryData(PERMISSIONS_KEY, permissions),
  })
}

/** Restart EvoFlux: macOS applies Screen Recording only to a fresh process. */
export function restartForPermissions(): Promise<void> {
  return invoke<void>('app_computer_restart')
}
