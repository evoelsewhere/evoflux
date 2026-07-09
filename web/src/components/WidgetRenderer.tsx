/**
 * WidgetRenderer — renders interactive HTML widgets inline.
 *
 * Uses morphdom for smooth DOM diffing during progressive streaming.
 * Supports dark mode via CSS variables and widget-to-chat communication.
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import { Loader2, MessageSquare } from 'lucide-react'
import morphdom from 'morphdom'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/useTeamStore'

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
  /** Callback when widget sends a prompt to chat */
  onSendPrompt?: (prompt: string) => void
  /** Session ID for sending prompts */
  sessionId?: string
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

// Wrap HTML in a full document with CSP, storage shim, and sendPrompt
function wrapHtml(html: string): string {
  const csp = buildCsp()
  const cspMeta = `<meta http-equiv="Content-Security-Policy" content="${csp.replaceAll('"', '&quot;')}">`
  
  // Storage shim for iframe isolation
  const storageShim = `<script>(function(){function createStorage(){var data=new Map();return{get length(){return data.size},key:function(index){return Array.from(data.keys())[index]||null},getItem:function(key){key=String(key);return data.has(key)?data.get(key):null},setItem:function(key,value){data.set(String(key),String(value));},removeItem:function(key){data.delete(key);},clear:function(){data.clear()}}}['localStorage','sessionStorage'].forEach(function(name){try{void window[name]}catch{Object.defineProperty(window,name,{value:createStorage(),configurable:true})}})})();</script>`
  
  // sendPrompt function for widget-to-chat communication
  const sendPromptScript = `<script>
    window.sendPrompt = function(prompt) {
      if (typeof prompt !== 'string' || !prompt.trim()) return;
      window.parent.postMessage({ type: 'widget_send_prompt', prompt: prompt.trim() }, '*');
    };
  </script>`

  // Reports content height to the parent so the iframe can grow to fit
  // instead of clipping content behind an internal scrollbar
  const resizeScript = `<script>(function(){
    function postHeight(){
      var h = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
      window.parent.postMessage({ type: 'widget_resize', height: h }, '*');
    }
    function init(){
      postHeight();
      if (window.ResizeObserver) {
        var ro = new ResizeObserver(postHeight);
        ro.observe(document.documentElement);
        if (document.body) ro.observe(document.body);
      }
      window.addEventListener('load', postHeight);
      setTimeout(postHeight, 50);
      setTimeout(postHeight, 300);
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
  })();</script>`

  if (/<head\b[^>]*>/i.test(html)) {
    return html.replace(/<head\b[^>]*>/i, (match) => `${match}${cspMeta}${storageShim}${sendPromptScript}${resizeScript}`)
  }
  return `<!doctype html><html><head>${cspMeta}${storageShim}${sendPromptScript}${resizeScript}</head><body>${html}</body></html>`
}

// Morphdom update with smooth diffing
function updateDomWithMorphdom(
  container: HTMLIFrameElement,
  html: string,
) {
  const doc = container.contentDocument
  if (!doc) return

  const fullHtml = wrapHtml(html)
  
  // Parse the new HTML
  const parser = new DOMParser()
  const newDoc = parser.parseFromString(fullHtml, 'text/html')
  
  // Get the body content
  const newBody = newDoc.body
  const currentBody = doc.body
  
  if (!currentBody || !newBody) {
    // Fallback to srcdoc if morphdom fails
    container.srcdoc = fullHtml
    return
  }
  
  // Use morphdom for smooth DOM diffing
  try {
    morphdom(currentBody, newBody, {
      onBeforeElUpdated: function(fromEl, toEl) {
        // Skip if elements are identical
        if (fromEl.isEqualNode(toEl)) return false
        return true
      },
      onNodeAdded: function(node) {
        // Add fade-in animation to new nodes
        if (node instanceof HTMLElement) {
          node.style.animation = 'widgetFadeIn 0.3s ease both'
        }
        return node
      },
    })
    
    // Execute scripts in the updated content
    executeScripts(doc)
  } catch (e) {
    // Fallback to srcdoc on error
    console.warn('Morphdom update failed, falling back to srcdoc:', e)
    container.srcdoc = fullHtml
  }
}

// Execute scripts in a document
function executeScripts(doc: Document) {
  const scripts = doc.querySelectorAll('script')
  scripts.forEach((oldScript) => {
    const newScript = doc.createElement('script')
    if (oldScript.src) {
      newScript.src = oldScript.src
    } else {
      newScript.textContent = oldScript.textContent
    }
    oldScript.parentNode?.replaceChild(newScript, oldScript)
  })
}

// Bounds for auto-sizing the iframe to its actual content height
const MIN_CONTENT_HEIGHT = 120
const MAX_CONTENT_HEIGHT = 2400

export function WidgetRenderer({
  html,
  isStreaming = false,
  title = 'Widget',
  width = 800,
  height = 600,
  loadingMessages = ['Loading visualization...'],
  className,
  onSendPrompt,
  sessionId,
}: WidgetRendererProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [isInitialized, setIsInitialized] = useState(false)
  const [contentHeight, setContentHeight] = useState<number | null>(null)
  const sendMessage = useTeamStore((s) => s.sendMessage)

  // Handle messages from iframe (sendPrompt, resize)
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type === 'widget_send_prompt' && event.data?.prompt) {
        const prompt = event.data.prompt as string
        if (onSendPrompt) {
          onSendPrompt(prompt)
        } else if (sessionId) {
          // Default: send message to chat
          sendMessage(prompt)
        }
      } else if (event.data?.type === 'widget_resize' && typeof event.data?.height === 'number') {
        const measured = event.data.height as number
        setContentHeight(Math.min(Math.max(measured, MIN_CONTENT_HEIGHT), MAX_CONTENT_HEIGHT))
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [onSendPrompt, sessionId, sendMessage])

  const effectiveHeight = contentHeight ?? height
  
  // Update iframe content when html changes
  useEffect(() => {
    if (iframeRef.current && html) {
      if (!isInitialized) {
        // First render: use srcdoc
        iframeRef.current.srcdoc = wrapHtml(html)
        // Mark initialized after current paint to avoid setState-in-effect lint
        requestAnimationFrame(() => setIsInitialized(true))
      } else {
        // Subsequent renders: use morphdom for smooth diffing
        updateDomWithMorphdom(iframeRef.current, html)
      }
    }
  }, [html, isInitialized])
  
  // Handle iframe load
  const handleLoad = useCallback(() => {
    // Scripts execute automatically
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
        <div className="flex items-center gap-2">
          {isStreaming && (
            <div className="flex items-center gap-1.5 text-xs text-(--color-text-muted)">
              <Loader2 size={12} className="animate-spin" />
              <span>Streaming...</span>
            </div>
          )}
          {onSendPrompt && (
            <div className="flex items-center gap-1 text-xs text-(--color-text-muted)">
              <MessageSquare size={12} />
              <span>Interactive</span>
            </div>
          )}
        </div>
      </div>
      
      {/* Widget content */}
      <iframe
        ref={iframeRef}
        title={title}
        width={width}
        height={effectiveHeight - 32} // Account for title bar
        sandbox="allow-scripts allow-same-origin"
        className="border-0 transition-[height] duration-150"
        onLoad={handleLoad}
        onError={handleError}
      />
      
      {/* CSS for animations */}
      <style>{`
        @keyframes widgetFadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}

export default WidgetRenderer
