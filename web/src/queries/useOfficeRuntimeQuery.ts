import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  cancelOfficeRuntimeInstall,
  dismissOfficeRuntimeError,
  getOfficeRuntimeStatus,
  installOfficeRuntime,
  uninstallOfficeRuntime,
} from '@/api/client'
import { queryKeys } from './keys'

/**
 * Exact Office rendering runtime. While a download is running the status is
 * the only place its progress lives, so the query polls until it settles.
 */
export function useOfficeRuntimeQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.settings.officeRuntime(),
    queryFn: getOfficeRuntimeStatus,
    enabled,
    staleTime: 30_000,
    refetchInterval: (query) => {
      const phase = query.state.data?.job?.phase
      return phase && phase !== 'failed' ? 1_000 : false
    },
  })
}

function useInvalidateOfficeRuntime() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: queryKeys.settings.officeRuntime() })
}

export function useInstallOfficeRuntimeMutation() {
  const invalidate = useInvalidateOfficeRuntime()
  return useMutation({ mutationFn: installOfficeRuntime, onSettled: invalidate })
}

export function useCancelOfficeRuntimeInstallMutation() {
  const invalidate = useInvalidateOfficeRuntime()
  return useMutation({ mutationFn: cancelOfficeRuntimeInstall, onSettled: invalidate })
}

export function useDismissOfficeRuntimeErrorMutation() {
  const invalidate = useInvalidateOfficeRuntime()
  return useMutation({ mutationFn: dismissOfficeRuntimeError, onSettled: invalidate })
}

export function useUninstallOfficeRuntimeMutation() {
  const invalidate = useInvalidateOfficeRuntime()
  return useMutation({ mutationFn: uninstallOfficeRuntime, onSettled: invalidate })
}
