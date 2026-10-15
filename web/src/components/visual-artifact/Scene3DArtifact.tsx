import { useEffect, useRef, useState } from 'react'
import type { VisualArtifactPayload } from '@/api/types'
import { createSceneRuntime, type SceneRuntime } from '@/lib/visual-artifact-three-runtime'

interface Props { artifact: VisualArtifactPayload; reducedMotion: boolean; resolvedTheme: 'light' | 'dark'; visible?: boolean }

export function Scene3DArtifact({ artifact, reducedMotion, resolvedTheme, visible = true }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const runtimeRef = useRef<SceneRuntime | null>(null)
  const [intersecting, setIntersecting] = useState(true)
  const [fallback, setFallback] = useState(false)
  const runtimeOptionsRef = useRef({ reducedMotion, visible: visible && intersecting })
  runtimeOptionsRef.current = { reducedMotion, visible: visible && intersecting }
  const nodes = artifact.scene?.nodes ?? []

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !artifact.scene) return
    let active = true
    let runtime: SceneRuntime | null = null
    setFallback(false)
    void import('three').then((three) => {
      if (!active) return
      runtime = createSceneRuntime(canvas, artifact.scene!, { reducedMotion: runtimeOptionsRef.current.reducedMotion, maxPixelRatio: 2, three })
      runtimeRef.current = runtime
      runtime.setVisible(runtimeOptionsRef.current.visible)
    }).catch(() => { if (active) setFallback(true) })
    return () => {
      active = false
      runtime?.dispose()
      runtimeRef.current = null
    }
  }, [artifact.artifactId, artifact.scene, resolvedTheme])

  useEffect(() => { runtimeRef.current?.setVisible(visible && intersecting) }, [visible, intersecting])
  useEffect(() => { runtimeRef.current?.setReducedMotion(reducedMotion) }, [reducedMotion])
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => setIntersecting(entry.isIntersecting), { threshold: 0.05 })
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [])

  return (
    <section className="my-2 overflow-hidden rounded-xl border border-(--color-border) bg-(--color-surface)" aria-label={`${artifact.title} 3D scene`}>
      <header className="flex items-start justify-between gap-3 px-4 py-3">
        <div><h3 className="text-sm font-semibold">{artifact.title}</h3><p className="mt-1 text-xs text-(--color-text-subtle)">{artifact.summary}</p></div>
        <button type="button" className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs" onClick={() => runtimeRef.current?.resetCamera()}>Reset view</button>
      </header>
      <div className="relative mx-3 mb-3 overflow-hidden rounded-lg bg-(--color-surface-subtle)">
        {!fallback && <canvas ref={canvasRef} tabIndex={0} aria-label="Interactive 3D scene. Drag to rotate or use arrow keys." className="h-72 w-full touch-none outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)" />}
        {fallback && <div role="img" aria-label="Static scene preview" className="flex min-h-72 flex-wrap items-center justify-center gap-3 p-4">
          {nodes.map((node) => <div key={node.id} className="flex size-20 items-center justify-center rounded-xl border border-(--color-border) bg-(--color-accent)/15 text-center text-xs text-(--color-text-primary) shadow-lg" title={`${node.geometry} · ${node.id}`}>{node.label || node.geometry}</div>)}
        </div>}
      </div>
      {fallback && <p className="px-4 pb-3 text-xs text-(--color-text-subtle)">3D is unavailable in this environment. Showing a labeled static scene preview.</p>}
      {!fallback && <p className="px-4 pb-3 text-xs text-(--color-text-subtle)">Drag to rotate; use arrow keys when the scene is focused. {reducedMotion ? 'Reduced motion is on; the scene stays still until you interact.' : 'Rendering pauses while this scene is offscreen.'}</p>}
    </section>
  )
}
