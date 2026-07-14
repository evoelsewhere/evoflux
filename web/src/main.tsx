import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installDesktopAuth } from './api/auth'
import { initTheme } from './lib/theme'
import { initAppearance } from './lib/appearance'

// Install the desktop session token interceptor *before* any other module
// has a chance to capture a reference to the original `window.fetch`.
installDesktopAuth()
initTheme()
initAppearance()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
