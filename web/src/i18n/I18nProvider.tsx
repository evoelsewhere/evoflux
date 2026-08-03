import { useLayoutEffect, type ReactNode } from 'react'

import { observeLocalizedDom } from './dom'
import { useLocale } from './react'

export function I18nProvider({ children }: { children: ReactNode }) {
  const locale = useLocale()

  useLayoutEffect(() => {
    return observeLocalizedDom(document.body, locale)
  }, [locale])

  return children
}
