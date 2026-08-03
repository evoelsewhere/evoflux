import { useMemo, useSyncExternalStore } from 'react'

import { translate } from './catalog'
import {
  getIntlLocale,
  getLocale,
  setLocale,
  subscribeLocale,
  type AppLocale,
} from './locale'

export function useLocale(): AppLocale {
  return useSyncExternalStore(subscribeLocale, getLocale, getLocale)
}

export function useI18n() {
  const locale = useLocale()
  return useMemo(() => ({
    locale,
    intlLocale: getIntlLocale(locale),
    setLocale,
    t: (key: string, values?: ReadonlyArray<string | number>) => translate(key, values, locale),
  }), [locale])
}
