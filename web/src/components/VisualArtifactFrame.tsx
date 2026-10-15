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
  onFrame?: (message: Extract<VisualArtifactBridgeMessage, { type: 'rendered_frame' | 'frame_error' }>) => void
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
  return `<script>(()=>{
let initialized=false,port=null,handlers=[],frameRenderer=null,recorder=null,tracks=[],exportQueue=Promise.resolve(),exportBytes=0,exportTimer=0,exportMime='',exportFailure='',exportStopState='complete';
const MAX_EXPORT_BYTES=150000000,MAX_CHUNK_BYTES=64000;
const safeTokens=t=>{if(!t||typeof t!=='object')return;for(const [k,v] of Object.entries(t)){if(/^--(?:color-|accent-|surface-|background|foreground|radius)/.test(k)&&typeof v==='string'&&v.length<=256)document.documentElement.style.setProperty(k,v)}};
const send=m=>{if(port)port.postMessage(m)};
const sendCommand=command=>{for(const fn of handlers){try{fn(command)}catch{}}};
const renderFrame=async command=>{const requestId=command.requestId,currentTimeMs=command.currentTimeMs;try{if(!frameRenderer)throw new Error('This explainer does not support frame rendering.');const canvas=document.querySelector('canvas[data-evoflux-motion-canvas]');if(!canvas)throw new Error('The marked motion canvas is missing.');await frameRenderer(currentTimeMs);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));const bitmap=await createImageBitmap(canvas);port.postMessage({type:'rendered_frame',requestId,currentTimeMs,bitmap},[bitmap])}catch(error){send({type:'frame_error',requestId,message:error instanceof Error?error.message:'The motion frame could not be rendered.'})}};
const cleanupExport=()=>{if(exportTimer)clearTimeout(exportTimer);exportTimer=0;tracks.forEach(track=>track.stop());tracks=[];recorder=null};
const finishExport=state=>{
  const activeRecorder=recorder;
  if(activeRecorder?.state==='recording'){activeRecorder.stop();return}
  exportQueue.then(()=>{
    if(exportFailure){send({type:'export_status',state:'error',message:exportFailure});return}
    if(state==='complete')send({type:'export_chunk',mimeType:activeRecorder?.mimeType||exportMime,bytes:new Uint8Array(),final:true});
    send({type:'export_status',state,...(state==='error'&&exportFailure?{message:exportFailure}:{})});
  }).catch(()=>send({type:'export_status',state:'error',message:'The video could not be finalized.'})).finally(cleanupExport);
};
const stopExport=(state,message)=>{exportStopState=state;if(message)exportFailure=message;if(recorder?.state==='recording'){recorder.stop();return}finishExport(state)};
const startExport=(mimeType,durationMs)=>{
  if(recorder){send({type:'export_status',state:'error',message:'A video export is already running.'});return false}
  const canvas=document.querySelector('canvas[data-evoflux-motion-canvas]');
  if(!canvas||!window.MediaRecorder||!MediaRecorder.isTypeSupported(mimeType)){send({type:'export_status',state:'error',message:'This browser cannot record the motion canvas in the selected format.'});return false}
  try{
    const stream=canvas.captureStream(30);tracks=stream.getTracks();exportMime=mimeType;exportBytes=0;exportFailure='';exportStopState='complete';exportQueue=Promise.resolve();
    recorder=new MediaRecorder(stream,{mimeType});
    recorder.addEventListener('dataavailable',event=>{
      if(!event.data?.size)return;
      exportQueue=exportQueue.then(async()=>{
        const bytes=new Uint8Array(await event.data.arrayBuffer());
        for(let offset=0;offset<bytes.length;offset+=MAX_CHUNK_BYTES){
          const chunk=bytes.slice(offset,Math.min(offset+MAX_CHUNK_BYTES,bytes.length));exportBytes+=chunk.length;
          if(exportBytes>MAX_EXPORT_BYTES){exportFailure='Export exceeded the 150 MB limit. Try a shorter animation.';if(recorder?.state==='recording')recorder.stop();return}
          send({type:'export_chunk',mimeType:recorder?.mimeType||exportMime,bytes:chunk,final:false});
        }
      }).catch(()=>{exportFailure='The recorded video data could not be read.';if(recorder?.state==='recording')recorder.stop()});
    });
    recorder.addEventListener('stop',()=>{if(exportTimer)clearTimeout(exportTimer);exportTimer=0;finishExport(exportFailure?'error':exportStopState)},{once:true});
    recorder.start(250);send({type:'export_status',state:'recording'});
    sendCommand('restart');sendCommand('play');
    exportTimer=setTimeout(()=>stopExport('complete'),Math.min(120000,durationMs+1500));
    return true;
  }catch{
    exportFailure='The browser could not start video recording.';stopExport('error',exportFailure);return false;
  }
};
const api={
  onCommand(fn){if(typeof fn==='function')handlers.push(fn)},
  registerFrameRenderer(fn){if(typeof fn!=='function')throw new TypeError('Frame renderer must be a function.');frameRenderer=fn;return()=>{if(frameRenderer===fn)frameRenderer=null}},
  reportPlayback(state,currentTimeMs){if(['playing','paused','ended'].includes(state)&&Number.isFinite(currentTimeMs)){send({type:'playback',state,currentTimeMs});if(state==='ended'&&recorder)stopExport('complete')}},
  startCanvasExport(mimeType){return startExport(mimeType,120000)}
};
Object.defineProperty(window,'evofluxArtifact',{value:Object.freeze(api),writable:false});
window.addEventListener('message',event=>{
  if(initialized||event.source!==window.parent||event.data?.type!=='evoflux-artifact-init'||!event.ports?.[0])return;
  initialized=true;port=event.ports[0];const config=event.data;safeTokens(config.tokens);document.documentElement.dataset.theme=config.resolvedTheme==='dark'?'dark':'light';document.documentElement.dataset.themePreference=String(config.theme||'system');document.documentElement.dataset.reducedMotion=String(Boolean(config.reducedMotion));
  port.onmessage=message=>{const data=message.data;if(data?.type==='theme'){safeTokens(data.tokens);document.documentElement.dataset.theme=data.resolvedTheme==='dark'?'dark':'light';document.documentElement.dataset.themePreference=String(data.theme||'system')}if(data?.type==='preferences'){document.documentElement.dataset.reducedMotion=String(Boolean(data.reducedMotion));if(data.reducedMotion)document.documentElement.style.setProperty('scroll-behavior','auto')}if(data?.type==='command'){if(data.command?.type==='render_frame')void renderFrame(data.command);else sendCommand(data.command)}if(data?.type==='export_request')startExport(data.mimeType,data.durationMs);if(data?.type==='export_cancel')stopExport('cancelled')};
  port.start();const canvas=document.querySelector('canvas[data-evoflux-motion-canvas]');send({type:'ready',motionCanvas:Boolean(canvas),frameRenderer:typeof frameRenderer==='function',canvasWidth:canvas?.width,canvasHeight:canvas?.height});const report=()=>send({type:'resize',height:Math.max(160,Math.min(2000,Math.ceil(document.documentElement.scrollHeight)))});new ResizeObserver(report).observe(document.documentElement);setTimeout(report,80)
});})();</script>`
}

// Pure serialization helper kept next to its iframe owner; exporting it makes the CSP easy to test.
// eslint-disable-next-line react-refresh/only-export-components
export function buildVisualArtifactSrcDoc(sourceHtml: string): string {
  const csp = FRAME_CSP.replaceAll('"', '&quot;')
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="viewport" content="width=device-width, initial-scale=1"><style>html,body{margin:0;min-height:100%;font-family:Inter,system-ui,sans-serif;color:var(--color-text-primary,inherit);background:var(--color-surface,transparent)}*{box-sizing:border-box}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;scroll-behavior:auto!important}}</style></head><body>${runtimeScript()}${sourceHtml}</body></html>`
}

export function VisualArtifactFrame({ artifact, theme, reducedMotion, onSendPrompt, onPlayback, onReady, onFrame, onPort }: Props) {
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
      if (message.type === 'rendered_frame' || message.type === 'frame_error') onFrame?.(message)
    }
    channel.port1.start()
    portRef.current = channel.port1
    onPort?.(channel.port1)
    frame.contentWindow.postMessage({
      type: 'evoflux-artifact-init', theme, resolvedTheme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
      reducedMotion, tokens: themeTokens(),
    }, '*', [channel.port2])
  }, [onFrame, onPlayback, onPort, onReady, onSendPrompt, reducedMotion, theme])

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
