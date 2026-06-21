import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getTitleGenerationSettings,
  updateTitleGenerationSettings,
  type TitleGenerationSettings,
} from '@/api/client'
import { queryKeys } from './keys'

export function useTitleGenerationSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.titleGeneration(),
    queryFn: getTitleGenerationSettings,
  })
}

export function useUpdateTitleGenerationSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TitleGenerationSettings) => updateTitleGenerationSettings(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.titleGeneration() })
    },
  })
}
