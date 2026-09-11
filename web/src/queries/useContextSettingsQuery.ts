import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getContextSettings, updateContextSettings } from '@/api/client'
import type { ContextOverrides, ContextSettings } from '@/api/types'
import { queryKeys } from './keys'

/** Every override unset — the base a merge falls back to before any load. */
const NO_OVERRIDES: ContextOverrides = {
  summary_trigger_tokens: null,
  summary_max_tokens: null,
  keep_recent_turns: null,
  tool_result_offload_chars: null,
  keep_recent_tool_batches: null,
}

/** `enabled` lets a lazily-opened surface (the context popover) defer the fetch. */
export function useContextSettingsQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.settings.context(),
    queryFn: getContextSettings,
    staleTime: 30_000,
    enabled,
  })
}

/**
 * Change one or more overrides.
 *
 * The endpoint replaces the whole object, so a partial change is merged onto
 * the cached settings first — otherwise editing the threshold from the
 * popover would silently clear every other override.
 */
export function useUpdateContextSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<ContextOverrides>) => {
      const current = client.getQueryData<ContextSettings>(
        queryKeys.settings.context(),
      )
      return updateContextSettings({
        ...NO_OVERRIDES,
        ...(current
          ? {
              summary_trigger_tokens: current.summary_trigger_tokens,
              summary_max_tokens: current.summary_max_tokens,
              keep_recent_turns: current.keep_recent_turns,
              tool_result_offload_chars: current.tool_result_offload_chars,
              keep_recent_tool_batches: current.keep_recent_tool_batches,
            }
          : {}),
        ...patch,
      })
    },
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.context(), data)
      // Each model's effective trigger is derived from these values
      // server-side and reaches the UI through the registry, so that cache
      // is stale the moment they change. Match every variant by prefix.
      void client.invalidateQueries({ queryKey: ['agentFiles', 'registry'] })
    },
  })
}
