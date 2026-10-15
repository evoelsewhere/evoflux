import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ThemePreference } from '@/lib/theme'
import type { VisualArtifactPayload } from '@/api/types'
import { parseVisualArtifactBridgeMessage, type VisualArtifactBridgeMessage } from '@/lib/visual-artifact-bridge'

interface Props {
  artifact: VisualArtifactPayload
  theme: ThemePreference
  reducedMotion: boolean
  onSendPrompt?: (prompt: string) => void
  onPlayback?: (message: Extract<VisualArtifactBridgeMessage, { type: 'playback' }>) => void
  onReady?: (message: Extract<VisualArtifactBridgeMessage, { type: 'ready' }>) => void
  onPort?: (port: MessagePort | null) => void
}

const FRAME_CSP = [
  "default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'",
  'img-src data: blob:', 'font-src data:', "connect-src 'none'", "frame-src 'none'",
  "object-src 'none'", "base-uri 'none'", "form-action 'none'", "navigate-to 'none'",
].join('; ')

function themeTokens(): Record<string, string> {
  const styles = getComputedStyle(document.documentElement)
  const tokens: Record<string, string> = {}
  for (let index = 0; index < styles.length && Object.keys(tokens).length < 160; index += 1) {
    const key = styles.item(index)
    if (!/^--(?:color-|accent-|surface-|background|foreground|radius)/.test(key)) continue
    const value = styles.getPropertyValue(key).trim()
    if (value && value.length <= 256) tokens[key] = value
  }
  return tokens
}

function runtimeScript(): string {
  return `<script>(()=>{let initialized=false,port=null,handlers=[],recorder=null,tracks=[],exportQueue=Promise.resolve(),exportBytes=0;const safeTokens=t=>{if(!t||typeof t!=='object')return;for(const [k,v] of Object.entries(t)){if(/^--(?:color-|accent-|surface-|background|foreground|radius)/.test(k)&&typeof v==='string'&&v.length<=256)document.documentElement.style.setProperty(k,v)}};const send=m=>{if(port)port.postMessage(m)};const startExport=mimeType=>{const canvas=document.querySelector('canvas[data-evoflux-motion-canvas]');if(!canvas||!window.MediaRecorder||!MediaRecorder.isTypeSupported(mimeType))return false;try{const stream=canvas.captureStream(30);tracks=stream.getTracks();recorder=new MediaRecorder(stream,{mimeType});exportBytes=0;recorder.addEventListener('dataavailable',event=>{if(!event.data?.size)return;exportQueue=exportQueue.then(async()=>{const bytes=new Uint8Array(await event.data.arrayBuffer());for(let offset=0;offset<bytes.length;offset+=64000){const chunk=bytes.slice(offset,Math.min(offset+64000,bytes.length));exportBytes+=chunk.length;if(exportBytes>150000000){if(recorder?.state==='recording')recorder.stop();return}send({type:'export_chunk',mimeType:recorder.mimeType||mimeType,bytes:chunk,final:false})}})});recorder.addEventListener('stop',()=>{exportQueue.finally(()=>{send({type:'export_chunk',mimeType:recorder?.mimeType||mimeType,bytes:new Uint8Array(),final:true});tracks.forEach(track=>track.stop());tracks=[];recorder=null})});recorder.start(400);setTimeout(()=>{if(recorder?.state==='recording')recorder.stop()},120000);return true}catch{tracks.forEach(track=>track.stop());tracks=[];recorder=null;return false}};const api={onCommand(fn){if(typeof fn==='function')handlers.push(fn)},reportPlayback(state,currentTimeMs){if(['playing','paused','ended'].includes(state)&&Number.isFinite(currentTimeMs))send({type:'playback',state,currentTimeMs})},startCanvasExport(mimeType){return startExport(mimeType)}};Object.defineProperty(window,'evofluxArtifact',{value:Object.freeze(api),writable:false});window.addEventListener('message',event=>{if(initialized||event.source!==window.parent||event.data?.type!=='evoflux-artifact-init'||!event.ports?.[0])return;initialized=true;port=event.ports[0];const config=event.data;safeTokens(config.tokens);document.documentElement.dataset.theme=config.resolvedTheme==='dark'?'dark':'light';document.documentElement.dataset.themePreference=String(config.theme||'system');document.documentElement.dataset.reducedMotion=String(Boolean(config.reducedMotion));port.onmessage=message=>{const data=message.data;if(data?.type==='theme'){safeTokens(data.tokens);document.documentElement.dataset.theme=data.resolvedTheme==='dark'?'dark':'light';document.documentElement.dataset.themePreference=String(data.theme||'system')}if(data?.type==='preferences'){document.documentElement.dataset.reducedMotion=String(Boolean(data.reducedMotion));if(data.reducedMotion)document.documentElement.style.setProperty('scroll-behavior','auto')}if(data?.type==='command')for(const fn of handlers){try{fn(data.command)}catch{}}if(data?.type==='export_request')startExport(data.mimeType)};port.start();send({type:'ready',motionCanvas:Boolean(document.querySelector('canvas[data-evoflux-motion-canvas]'))});const report=()=>send({type:'resize',height:Math.max(160,Math.min(2000,Math.ceil(document.documentElement.scrollHeight)))});new ResizeObserver(report).observe(document.documentElement);setTimeout(report,80)});})();</script>`
}

// Pure serialization helper kept next to its iframe owner; exporting it makes the CSP easy to test.
// eslint-disable-next-line react-refresh/only-export-components
export function buildVisualArtifactSrcDoc(sourceHtml: string): string {
  const csp = FRAME_CSP.replaceAll('"', '&quot;')
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="viewport" content="width=device-width, initial-scale=1"><style>html,body{margin:0;min-height:100%;font-family:Inter,system-ui,sans-serif;color:var(--color-text-primary,inherit);background:var(--color-surface,transparent)}*{box-sizing:border-box}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;scroll-behavior:auto!important}}</style></head><body>${sourceHtml}${runtimeScript()}</body></html>`
}

export function VisualArtifactFrame({ artifact, theme, reducedMotion, onSendPrompt, onPlayback, onReady, onPort }: Props) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const portRef = useRef<MessagePort | null>(null)
  const [height, setHeight] = useState(420)
  const srcDoc = useMemo(() => artifact.sourceHtml ? buildVisualArtifactSrcDoc(artifact.sourceHtml) : '', [artifact.sourceHtml])

  const init = useCallback(() => {
    const frame = frameRef.current
    if (!frame?.contentWindow || !('MessageChannel' in window)) return
    portRef.current?.close()
    const channel = new MessageChannel()
    channel.port1.onmessage = (event: MessageEvent<unknown>) => {
      const message = parseVisualArtifactBridgeMessage(event.data)
      if (!message) return
      if (message.type === 'resize') setHeight(message.height)
      if (message.type === 'send_prompt') onSendPrompt?.(message.prompt)
      if (message.type === 'playback') onPlayback?.(message)
      if (message.type === 'ready') onReady?.(message)
    }
    channel.port1.start()
    portRef.current = channel.port1
    onPort?.(channel.port1)
    frame.contentWindow.postMessage({
      type: 'evoflux-artifact-init', theme, resolvedTheme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
      reducedMotion, tokens: themeTokens(),
    }, '*', [channel.port2])
  }, [onPlayback, onPort, onReady, onSendPrompt, reducedMotion, theme])

  useEffect(() => {
    const port = portRef.current
    if (port) {
      port.postMessage({ type: 'theme', theme, resolvedTheme: document.documentElement.classList.contains('dark') ? 'dark' : 'light', tokens: themeTokens() })
      port.postMessage({ type: 'preferences', reducedMotion })
    }
  }, [theme, reducedMotion])

  useEffect(() => () => {
    portRef.current?.close()
    portRef.current = null
    onPort?.(null)
  }, [onPort])

  return (
    <iframe
      ref={frameRef}
      title={artifact.title}
      sandbox="allow-scripts"
      srcDoc={srcDoc}
      onLoad={init}
      className="w-full rounded-xl border border-(--color-border) bg-(--color-surface)"
      style={{ height }}
      referrerPolicy="no-referrer"
    />
  )
}
