import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installDesktopAuth } from './api/auth'
import { initTheme } from './lib/theme'
import { initAppearance } from './lib/appearance'
import { I18nProvider, initLocale } from './i18n'

// Install the desktop session token interceptor *before* any other module
// has a chance to capture a reference to the original `window.fetch`.
installDesktopAuth()
initTheme()
initAppearance()
initLocale()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
)
