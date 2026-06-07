import { useProviderStore, type ProviderInstance } from '../stores/providerStore'

export function getProviderFromStore(providerId?: string): ProviderInstance | undefined {
  const store = useProviderStore.getState()
  if (providerId) {
    return store.providers.find(p => p.id === providerId)
  }
  return store.getDefaultProvider()
}
