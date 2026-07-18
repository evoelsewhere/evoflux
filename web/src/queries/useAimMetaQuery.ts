import { useQuery } from '@tanstack/react-query'
import { getAimMeta } from '@/api/client'
import { queryKeys } from './keys'

/** AIM phase vocabulary from the backend (GET /aim/meta) — the source of
 * truth for phase order, labels, and the phase→next-pipeline map. It's
 * project-independent and effectively static, so it's cached hard; the UI
 * reads it instead of duplicating the phase set (kept in sync with the
 * backend `VALID_PHASES`). */
export function useAimMetaQuery() {
  return useQuery({
    queryKey: queryKeys.projects.aimMeta(),
    queryFn: getAimMeta,
    staleTime: 5 * 60_000,
  })
}
