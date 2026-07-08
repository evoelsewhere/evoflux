/**
 * WidgetRenderer — renders interactive HTML widgets inline.
 *
 * Uses morphdom for smooth DOM diffing during progressive streaming.
 * Supports dark mode via CSS variables.
 */

import { useEffect, useRef, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface WidgetRendererProps {
  /** HTML content to render */
  html: string
  /** Whether widget is still streaming */
  isStreaming?: boolean
  /** Widget title */
  title?: string
  /** Widget width */
  width?: number
  /** Widget height */
  height?: number
  /** Loading messages to show during streaming */
  loadingMessages?: string[]
  /** Additional CSS classes */
  className?: string
}

// CDN allowlist for scripts
const ALLOWED_CDNS = [
  'cdnjs.cloudflare.com',
  'cdn.jsdelivr.net',
  'unpkg.com',
  'esm.sh',
]

// Build CSP string
function buildCsp(): string {
  const scriptSrc = ["'self'", 'blob:', 'data:', ...ALLOWED_CDNS, "'unsafe-inline'", "'unsafe-eval'"]
  const styleSrc = ["'self'", 'blob:', 'data:', "'unsafe-inline'"]
  const imgSrc = ["'self'", 'blob:', 'data:']
  const fontSrc = ["'self'", 'blob:', 'data:']
  const connectSrc = ["'self'"]
  const frameSrc = ["'self'"]
  
  return [
    "default-src 'none'",
    `script-src ${scriptSrc.join(' ')}`,
    `style-src ${styleSrc.join(' ')}`,
    `img-src ${imgSrc.join(' ')}`,
    `font-src ${fontSrc.join(' ')}`,
    `connect-src ${connectSrc.join(' ')}`,
    `frame-src ${frameSrc.join(' ')}`,
    "object-src 'none'",
    "base-uri 'self'",
  ].join('; ')
}

// Wrap HTML in a full document with CSP and storage shim
function wrapHtml(html: string): string {
  const csp = buildCsp()
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${csp.replaceAll('"', '&quot;')}">`
  
  // Storage shim for iframe isolation
  const storageShim = `<script>(function(){function createStorage(){var data=new Map();return{get length(){return data.size},key:function(index){return Array.from(data.keys())[index]||null},getItem:function(key){key=String(key);return data.has(key)?data.get(key):null},setItem:function(key,value){data.set(String(key),String(value));},removeItem:function(key){data.delete(key);},clear:function(){data.clear()}}}['localStorage','sessionStorage'].forEach(function(name){try{void window[name]}catch{Object.defineProperty(window,name,{value:createStorage(),configurable:true})}})})();</script>`
  
  if (/<head\b[^>]*>/i.test(html)) {
    return html.replace(/<head\b[^>]*>/i, (match) => `${match}${cspMeta}${storageShim}`)
  }
  return `<!doctype html><html><head>${cspMeta}${storageShim}</head><body>${html}</body></html>`
}

// Morphdom-like DOM diffing (simplified version)
function updateDom(container: HTMLIFrameElement, html: string) {
  const doc = container.contentDocument
  if (!doc) return
  
  // For simplicity, we'll use srcdoc for now
  // In production, use morphdom for smooth diffs
  container.srcdoc = wrapHtml(html)
}

export function WidgetRenderer({
  html,
  isStreaming = false,
  title = 'Widget',
  width = 800,
  height = 600,
  loadingMessages = ['Loading visualization...'],
  className,
}: WidgetRendererProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  
  // Update iframe content when html changes
  useEffect(() => {
    if (iframeRef.current && html) {
      updateDom(iframeRef.current, html)
    }
  }, [html])
  
  // Handle iframe load
  const handleLoad = useCallback(() => {
    // Scripts execute automatically via srcdoc
  }, [])
  
  // Handle errors
  const handleError = useCallback((e: React.SyntheticEvent<HTMLIFrameElement, Event>) => {
    console.error('Widget rendering error:', e)
  }, [])
  
  // Loading state
  if (isStreaming && !html) {
    return (
      <div
        ref={containerRef}
        className={cn(
          'flex items-center justify-center rounded-lg border border-(--color-border) bg-(--color-background)',
          className,
        )}
        style={{ width, height }}
      >
        <div className="flex flex-col items-center gap-2 text-(--color-text-muted)">
          <Loader2 size={24} className="animate-spin" />
          <span className="text-sm">{loadingMessages[0]}</span>
        </div>
      </div>
    )
  }
  
  return (
    <div
      ref={containerRef}
      className={cn(
        'relative overflow-hidden rounded-lg border border-(--color-border)',
        className,
      )}
    >
      {/* Title bar */}
      <div className="flex items-center justify-between border-b border-(--color-border) bg-(--color-background-secondary) px-3 py-1.5">
        <span className="text-xs font-medium text-(--color-text-muted)">{title}</span>
        {isStreaming && (
          <div className="flex items-center gap-1.5 text-xs text-((--color-text-muted))">
            <Loader2 size={12} className="animate-spin" />
            <span>Streaming...</span>
          </div>
        )}
      </div>
      
      {/* Widget content */}
      <iframe
        ref={iframeRef}
        title={title}
        width={width}
        height={height - 32} // Account for title bar
        sandbox="allow-scripts allow-same-origin"
        className="border-0"
        onLoad={handleLoad}
        onError={handleError}
      />
    </div>
  )
}

export default WidgetRenderer
