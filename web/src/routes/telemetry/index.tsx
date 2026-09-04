/**
 * `/telemetry` — kept only so existing links and bookmarks land somewhere.
 *
 * Telemetry used to be two pages: this standalone one, with its own sidebar
 * carrying Overview, Models, Tools and Traces, and a Settings page with only
 * Overview and Traces. Nothing linked here, so half the monitoring views
 * were reachable by typing a URL. All four are Settings tabs now.
 *
 * Settings is an overlay rather than a route, so this opens it and returns
 * to the app shell instead of redirecting to a path that does not exist.
 */
import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'

import { useUIStore } from '@/stores/useUIStore'

export function TelemetryRedirect() {
  const navigate = useNavigate()

  useEffect(() => {
    useUIStore.getState().openSettings('telemetry')
    void navigate({ to: '/', replace: true })
  }, [navigate])

  return null
}
