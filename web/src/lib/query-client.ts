import { QueryClient } from '@tanstack/react-query'
import { ApiValidationError } from '@/api/client/_shared'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      gcTime: 1000 * 60 * 10, // 10 minutes
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof DOMException && ['AbortError', 'TimeoutError'].includes(error.name)) return false
        if (error instanceof ApiValidationError && error.status < 500) return false
        return failureCount < 1
      },
    },
  },
})
