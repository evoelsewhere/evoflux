import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from 'react'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SpatialEdge, SpatialGraphData, SpatialNode } from './repoGraphSpatialData'

interface ViewState {
  scale: number
  panX: number
  panY: number
}

function simulateStep(
  nodes: SpatialNode[],
  edgeSrcTgt: Array<[SpatialNode, SpatialNode]>,
  repoCenters: Map<string, { x: number; y: number }>,
) {
  const repulsion = 1200
  const springLen = { intra: 60, cross: 120 }
  const springK = { intra: 0.003, cross: 0.0015 }
  const clusterK = 0.002
  const centerK = 0.0008
  const damping = 0.88

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i]
      const b = nodes[j]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const distSq = Math.max(dx * dx + dy * dy, 1)
      const dist = Math.sqrt(distSq)
      const force = repulsion / distSq
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      const invA = 1 / a.mass
      const invB = 1 / b.mass
      a.vx += fx * invA
      a.vy += fy * invA
      b.vx -= fx * invB
      b.vy -= fy * invB
    }
  }

  for (const [a, b] of edgeSrcTgt) {
    const dx = b.x - a.x
    const dy = b.y - a.y
    const dist = Math.hypot(dx, dy) || 0.1
    const isRepoEdge = a.repo || b.repo
    const len = isRepoEdge ? springLen.cross : springLen.intra
    const k = isRepoEdge ? springK.cross : springK.intra
    const force = (dist - len) * k
    const fx = (dx / dist) * force
    const fy = (dy / dist) * force
    const invA = 1 / a.mass
    const invB = 1 / b.mass
    a.vx += fx * invA
    a.vy += fy * invA
    b.vx -= fx * invB
    b.vy -= fy * invB
  }

  for (const node of nodes) {
    if (node.repo) {
      node.vx += -node.x * centerK * 2
      node.vy += -node.y * centerK * 2
    } else {
      const center = repoCenters.get(node.workspaceId)
      if (center) {
        node.vx += (center.x - node.x) * clusterK
        node.vy += (center.y - node.y) * clusterK
      }
      node.vx += -node.x * centerK
      node.vy += -node.y * centerK
    }
    node.vx *= damping
    node.vy *= damping
    node.x += node.vx
    node.y += node.vy
  }
}

function edgeColor(edge: SpatialEdge): string {
  if (!edge.crossRepo) return 'rgba(148,163,184,0.35)'
  switch (edge.status) {
    case 'resolved':
      return 'rgba(16,185,129,0.55)'
    case 'unresolved':
      return 'rgba(244,63,94,0.45)'
    case 'rejected':
      return 'rgba(115,115,115,0.25)'
    default:
      return 'rgba(148,163,184,0.3)'
  }
}

interface RepoGraphSpatialProps {
  data: SpatialGraphData
  searchQuery: string
  selectedId: string | null
  onSelect: (id: string | null) => void
  hiddenRepoIds: Set<string>
  className?: string
}

export function RepoGraphSpatial({ data, searchQuery, selectedId, onSelect, hiddenRepoIds, className }: RepoGraphSpatialProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [view, setView] = useState<ViewState>({ scale: 1, panX: 0, panY: 0 })
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null)
  const viewRef = useRef(view)
  viewRef.current = view

  const visibleNodes = useMemo(() => {
    return data.nodes.filter((n) => !hiddenRepoIds.has(n.workspaceId))
  }, [data.nodes, hiddenRepoIds])

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes])

  const visibleEdges = useMemo(() => {
    return data.edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
  }, [data.edges, visibleNodeIds])

  const edgePairs = useMemo(() => {
    const byId = new Map<string, SpatialNode>()
    for (const n of visibleNodes) byId.set(n.id, n)
    const pairs: Array<[SpatialNode, SpatialNode]> = []
    for (const e of visibleEdges) {
      const a = byId.get(e.source)
      const b = byId.get(e.target)
      if (a && b) pairs.push([a, b])
    }
    return pairs
  }, [visibleNodes, visibleEdges])

  const repoCenters = useMemo(() => {
    const centers = new Map<string, { x: number; y: number }>()
    for (const node of visibleNodes) {
      if (node.repo) centers.set(node.workspaceId, { x: node.x, y: node.y })
    }
    return centers
  }, [visibleNodes])

  const visibleNodeById = useMemo(() => {
    const map = new Map<string, SpatialNode>()
    for (const n of visibleNodes) map.set(n.id, n)
    return map
  }, [visibleNodes])

  const query = searchQuery.trim().toLowerCase()
  const matchIds = useMemo(() => {
    if (!query) return new Set<string>()
    const ids = new Set<string>()
    for (const n of visibleNodes) {
      if (n.label.toLowerCase().includes(query) || n.fullLabel.toLowerCase().includes(query)) {
        ids.add(n.id)
      }
    }
    return ids
  }, [query, visibleNodes])

  useEffect(() => {
    if (matchIds.size > 0) {
      let sumX = 0
      let sumY = 0
      let count = 0
      for (const id of matchIds) {
        const node = visibleNodeById.get(id)
        if (node && !node.repo) {
          sumX += node.x
          sumY += node.y
          count++
        }
      }
      if (count > 0) {
        const cx = sumX / count
        const cy = sumY / count
        const canvas = canvasRef.current
        if (canvas) {
          setView({ scale: 2, panX: -cx * 2, panY: -cy * 2 })
        }
      }
    }
  }, [matchIds, visibleNodeById])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
      }
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.width = size.width
    canvas.height = size.height
  }, [size])

  useEffect(() => {
    let raf = 0
    const step = () => {
      simulateStep(visibleNodes, edgePairs, repoCenters)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [visibleNodes, edgePairs, repoCenters])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const draw = () => {
      const v = viewRef.current
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.save()
      ctx.translate(v.panX + canvas.width / 2, v.panY + canvas.height / 2)
      ctx.scale(v.scale, v.scale)

      const searching = matchIds.size > 0

      ctx.save()
      ctx.strokeStyle = 'rgba(71,85,105,0.1)'
      ctx.lineWidth = 1
      const grid = 80
      const left = (-v.panX - canvas.width / 2) / v.scale
      const right = (-v.panX + canvas.width / 2) / v.scale
      const top = (-v.panY - canvas.height / 2) / v.scale
      const bottom = (-v.panY + canvas.height / 2) / v.scale
      for (let x = Math.floor(left / grid) * grid; x < right; x += grid) {
        ctx.beginPath()
        ctx.moveTo(x, top)
        ctx.lineTo(x, bottom)
        ctx.stroke()
      }
      for (let y = Math.floor(top / grid) * grid; y < bottom; y += grid) {
        ctx.beginPath()
        ctx.moveTo(left, y)
        ctx.lineTo(right, y)
        ctx.stroke()
      }
      ctx.restore()

      for (const edge of visibleEdges) {
        const src = visibleNodeById.get(edge.source)
        const dst = visibleNodeById.get(edge.target)
        if (!src || !dst) continue
        let alpha = 1
        if (searching) {
          const srcMatch = matchIds.has(src.id)
          const dstMatch = matchIds.has(dst.id)
          alpha = srcMatch || dstMatch ? 0.8 : 0.04
        }
        if (alpha < 0.03) continue
        ctx.beginPath()
        ctx.moveTo(src.x, src.y)
        ctx.lineTo(dst.x, dst.y)
        ctx.strokeStyle = edgeColor(edge)
        ctx.globalAlpha = alpha
        ctx.lineWidth = edge.crossRepo ? 1.6 : 0.8
        ctx.stroke()
        ctx.globalAlpha = 1
      }

      const labelNodes: SpatialNode[] = []
      for (const node of visibleNodes) {
        const isMatch = matchIds.has(node.id)
        const isDimmed = searching && !isMatch
        const isSelected = selectedId === node.id
        const isHover = hoverId === node.id
        const r = node.radius * (isSelected || isHover ? 1.35 : 1)
        const alpha = isDimmed ? 0.12 : 1

        ctx.save()
        ctx.globalAlpha = alpha
        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
        ctx.fillStyle = node.baseColor
        ctx.shadowColor = node.glowColor
        ctx.shadowBlur = node.repo ? 28 : 12
        ctx.fill()
        ctx.shadowBlur = 0

        if (isMatch && searching && !node.repo) {
          ctx.strokeStyle = '#fbbf24'
          ctx.lineWidth = 2.5
          ctx.shadowColor = '#fbbf24'
          ctx.shadowBlur = 10
          ctx.stroke()
          ctx.shadowBlur = 0
        }

        if (isSelected || isHover) {
          ctx.strokeStyle = '#e2e8f0'
          ctx.lineWidth = 2
          ctx.stroke()
        }

        if (node.repo) {
          ctx.fillStyle = 'rgba(2,6,23,0.7)'
          ctx.beginPath()
          ctx.arc(node.x, node.y, r * 0.55, 0, Math.PI * 2)
          ctx.fill()
        }

        ctx.restore()

        if ((node.repo || r * v.scale > 6) && !isDimmed) {
          labelNodes.push(node)
        }
      }

      for (const node of labelNodes) {
        ctx.save()
        ctx.globalAlpha = selectedId === node.id || hoverId === node.id || matchIds.has(node.id) ? 1 : 0.75
        ctx.fillStyle = node.textColor
        ctx.font = node.repo ? '600 11px JetBrains Mono, monospace' : '400 9px JetBrains Mono, monospace'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        const label = node.repo
          ? node.label
          : node.label.length > 22
            ? `${node.label.slice(0, 22)}…`
            : node.label
        ctx.fillText(label, node.x, node.y + node.radius + 4)
        ctx.restore()
      }

      ctx.restore()
    }

    let raf = 0
    const loop = () => {
      draw()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [canvasRef, visibleNodes, visibleEdges, visibleNodeById, selectedId, hoverId, matchIds])

  const screenToWorld = (sx: number, sy: number) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const v = viewRef.current
    return {
      x: (sx - rect.left - v.panX - canvas.width / 2) / v.scale,
      y: (sy - rect.top - v.panY - canvas.height / 2) / v.scale,
    }
  }

  const findNodeAt = (sx: number, sy: number): SpatialNode | null => {
    const { x, y } = screenToWorld(sx, sy)
    let best: SpatialNode | null = null
    let bestDist = Infinity
    for (const node of visibleNodes) {
      const hitR = node.radius * (selectedId === node.id || hoverId === node.id ? 1.5 : 1) + 4 / viewRef.current.scale
      const dist = Math.hypot(node.x - x, node.y - y)
      if (dist < hitR && dist < bestDist) {
        best = node
        bestDist = dist
      }
    }
    return best
  }

  const onWheel = (e: ReactWheelEvent) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const worldBefore = screenToWorld(e.clientX, e.clientY)
    const factor = e.deltaY < 0 ? 1.12 : 0.89
    const newScale = Math.min(6, Math.max(0.15, viewRef.current.scale * factor))
    const newPanX = mx - worldBefore.x * newScale - canvas.width / 2
    const newPanY = my - worldBefore.y * newScale - canvas.height / 2
    setView({ scale: newScale, panX: newPanX, panY: newPanY })
  }

  const onPointerDown = (e: ReactPointerEvent) => {
    const hit = findNodeAt(e.clientX, e.clientY)
    if (hit) {
      onSelect(hit.id)
      dragRef.current = null
      return
    }
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: viewRef.current.panX, panY: viewRef.current.panY }
  }

  const onPointerMove = (e: ReactPointerEvent) => {
    if (dragRef.current) {
      setView((v) => ({
        ...v,
        panX: dragRef.current!.panX + (e.clientX - dragRef.current!.startX),
        panY: dragRef.current!.panY + (e.clientY - dragRef.current!.startY),
      }))
      return
    }
    const hit = findNodeAt(e.clientX, e.clientY)
    setHoverId(hit?.id ?? null)
  }

  const onPointerUp = () => {
    dragRef.current = null
  }

  const resetView = () => setView({ scale: 1, panX: 0, panY: 0 })
  const zoomIn = () => setView((v) => ({ ...v, scale: Math.min(6, v.scale * 1.25) }))
  const zoomOut = () => setView((v) => ({ ...v, scale: Math.max(0.15, v.scale * 0.8) }))

  const matchCount = matchIds.size

  return (
    <div ref={containerRef} className={cn('relative h-full w-full overflow-hidden', className)}>
      <canvas
        ref={canvasRef}
        className={cn('absolute inset-0 cursor-grab touch-none active:cursor-grabbing', hoverId && 'cursor-pointer')}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      />
      <div className="pointer-events-none absolute inset-x-0 bottom-3 left-3 z-10 flex items-center gap-2">
        <div className="pointer-events-auto flex items-center gap-3 rounded-md border border-(--color-border) bg-(--bg-card)/90 px-3 py-1.5 text-[10px] text-(--color-text-muted) backdrop-blur-sm">
          <span>{visibleNodes.length.toLocaleString()} visible</span>
          <span className="text-(--color-border)">|</span>
          <span>{visibleEdges.length.toLocaleString()} edges</span>
          {query && matchCount > 0 && (
            <>
              <span className="text-(--color-border)">|</span>
              <span className="text-amber-400">{matchCount} matches</span>
            </>
          )}
        </div>
      </div>
      <div className="absolute bottom-3 right-3 z-20 flex flex-col gap-1 rounded-md border border-(--color-border) bg-(--bg-card)/90 p-1 backdrop-blur-sm">
        <button type="button" onClick={zoomIn} className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key)">
          <Plus size={14} />
        </button>
        <button type="button" onClick={zoomOut} className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key)">
          <Minus size={14} />
        </button>
        <button type="button" onClick={resetView} className="flex h-7 w-7 items-center justify-center rounded text-(--color-text-muted) hover:bg-(--bg-key)">
          <RotateCcw size={13} />
        </button>
      </div>
    </div>
  )
}
