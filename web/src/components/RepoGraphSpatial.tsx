import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from 'react'
import { Focus, Minus, Plus, RotateCcw } from 'lucide-react'
import { getIntlLocale } from '@/i18n'
import { useThemePreference } from '@/hooks/useThemePreference'
import { cn } from '@/lib/utils'
import type { SpatialEdge, SpatialGraphData, SpatialNode } from './repoGraphSpatialData'

interface ViewState {
  scale: number
  panX: number
  panY: number
}

interface LayoutNode {
  node: SpatialNode
  x: number
  y: number
  radius: number
  color: string
  degree: number
}

const WORLD_SIZE = 1_080
const EDGE_COLORS: Record<string, string> = {
  calls: '#a855f7',
  contains: '#6366f1',
  imports: '#06b6d4',
  references: '#ec4899',
  inherits: '#f59e0b',
  implements: '#22c55e',
  uses: '#14b8a6',
}

const LIGHT_EDGE_COLORS: Record<string, string> = {
  calls: '#7c3aed',
  contains: '#4f46e5',
  imports: '#0891b2',
  references: '#db2777',
  inherits: '#d97706',
  implements: '#059669',
  uses: '#0f766e',
}

const KIND_COLORS: Record<string, string> = {
  repo: '#f8fafc',
  class: '#f43f5e',
  interface: '#fb7185',
  struct: '#f97316',
  function: '#a855f7',
  method: '#22d3ee',
  module: '#facc15',
  namespace: '#eab308',
  variable: '#84cc16',
  property: '#34d399',
  field: '#10b981',
  enum: '#f59e0b',
}

const LIGHT_KIND_COLORS: Record<string, string> = {
  repo: '#1f2937',
  class: '#e11d48',
  interface: '#e11d48',
  struct: '#ea580c',
  function: '#7c3aed',
  method: '#0891b2',
  module: '#ca8a04',
  namespace: '#a16207',
  variable: '#65a30d',
  property: '#059669',
  field: '#059669',
  enum: '#d97706',
}

function stableHash(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function unitHash(value: string): number {
  return stableHash(value) / 0xffffffff
}

function colorForNode(node: SpatialNode, darkMode: boolean): string {
  return (darkMode ? KIND_COLORS : LIGHT_KIND_COLORS)[node.kind] ?? node.baseColor ?? (darkMode ? '#60a5fa' : '#2563eb')
}

function colorForEdge(edge: SpatialEdge, darkMode: boolean): string {
  if (edge.crossRepo) return darkMode ? '#2dd4bf' : '#0f766e'
  return (darkMode ? EDGE_COLORS : LIGHT_EDGE_COLORS)[edge.kind] ?? (darkMode ? '#64748b' : '#64748b')
}

function drawShape(
  context: CanvasRenderingContext2D,
  layout: LayoutNode,
  radius: number,
) {
  const { node, x, y } = layout
  context.beginPath()
  if (node.repo) {
    context.arc(x, y, radius, 0, Math.PI * 2)
    return
  }
  if (['class', 'interface', 'struct', 'enum'].includes(node.kind)) {
    context.roundRect(x - radius, y - radius, radius * 2, radius * 2, 1.5)
    return
  }
  if (['module', 'namespace'].includes(node.kind)) {
    context.moveTo(x, y - radius * 1.25)
    context.lineTo(x + radius * 1.25, y)
    context.lineTo(x, y + radius * 1.25)
    context.lineTo(x - radius * 1.25, y)
    context.closePath()
    return
  }
  context.arc(x, y, radius, 0, Math.PI * 2)
}

function shortLabel(value: string): string {
  return value.length > 28 ? `${value.slice(0, 27)}…` : value
}

interface RepoGraphSpatialProps {
  data: SpatialGraphData
  searchQuery: string
  selectedId: string | null
  onSelect: (id: string | null) => void
  hiddenRepoIds: Set<string>
  className?: string
}

export function RepoGraphSpatial({
  data,
  searchQuery,
  selectedId,
  onSelect,
  hiddenRepoIds,
  className,
}: RepoGraphSpatialProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const dragRef = useRef<{
    x: number
    y: number
    panX: number
    panY: number
    moved: boolean
  } | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [view, setView] = useState<ViewState>({ scale: 1, panX: 0, panY: 0 })
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [enabledKinds, setEnabledKinds] = useState<Set<string>>(new Set())
  const { resolved } = useThemePreference()
  const darkMode = resolved === 'dark'
  const query = searchQuery.trim().toLowerCase()

  const graph = useMemo(() => {
    const repositories = data.nodes.filter(
      (node) => node.repo && !hiddenRepoIds.has(node.workspaceId),
    )
    const symbols = data.nodes.filter(
      (node) => !node.repo && !hiddenRepoIds.has(node.workspaceId),
    )
    const symbolIds = new Set(symbols.map((node) => node.id))
    const allEdges = data.edges.filter(
      (edge) => symbolIds.has(edge.source) && symbolIds.has(edge.target),
    )
    const edgeKindCounts = new Map<string, number>()
    for (const edge of allEdges) {
      edgeKindCounts.set(edge.kind, (edgeKindCounts.get(edge.kind) ?? 0) + 1)
    }
    const relationKinds = [...edgeKindCounts.entries()]
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6)
    const edges = enabledKinds.size === 0
      ? allEdges
      : allEdges.filter((edge) => enabledKinds.has(edge.kind))
    const degree = new Map<string, number>()
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
    }
    const maxDegree = Math.max(1, ...degree.values())
    const repositoryIndex = new Map(
      repositories.map((repository, index) => [repository.workspaceId, index]),
    )
    const repositoryCount = Math.max(1, repositories.length)
    const layoutNodes: LayoutNode[] = []

    for (const repository of repositories) {
      const index = repositoryIndex.get(repository.workspaceId) ?? 0
      const angle = (index / repositoryCount) * Math.PI * 2 - Math.PI / 2
      const anchorRadius = repositoryCount === 1 ? 0 : Math.min(155, 72 * repositoryCount)
      layoutNodes.push({
        node: repository,
        x: Math.cos(angle) * anchorRadius,
        y: Math.sin(angle) * anchorRadius,
        radius: 10,
        color: repository.baseColor,
        degree: 0,
      })
    }

    for (const node of symbols) {
      const index = repositoryIndex.get(node.workspaceId) ?? 0
      const repositoryAngle = (index / repositoryCount) * Math.PI * 2 - Math.PI / 2
      const anchorRadius = repositoryCount === 1 ? 0 : Math.min(155, 72 * repositoryCount)
      const anchorX = Math.cos(repositoryAngle) * anchorRadius
      const anchorY = Math.sin(repositoryAngle) * anchorRadius
      const nodeDegree = degree.get(node.id) ?? 0
      const importance = Math.sqrt(nodeDegree / maxDegree)
      const fileSeed = unitHash(`${node.workspaceId}:${node.data && 'file_path' in node.data ? node.data.file_path : node.fullLabel}`)
      const nodeSeed = unitHash(node.id)
      const goldenAngle = Math.PI * (3 - Math.sqrt(5))
      const localAngle = nodeSeed * Math.PI * 2 + fileSeed * goldenAngle * 7
      const radius = 45 + (1 - importance) * 275 + fileSeed * 62
      const clusterBias = 0.72 + unitHash(`${node.id}:cluster`) * 0.35
      layoutNodes.push({
        node,
        x: anchorX + Math.cos(localAngle) * radius * clusterBias,
        y: anchorY + Math.sin(localAngle) * radius * clusterBias,
        radius: Math.min(7.5, 2.1 + Math.sqrt(nodeDegree) * 0.7 + (node.kind === 'class' ? 1.2 : 0)),
        color: colorForNode(node, darkMode),
        degree: nodeDegree,
      })
    }

    const nodeById = new Map(layoutNodes.map((layout) => [layout.node.id, layout]))
    const matchIds = new Set<string>()
    if (query) {
      for (const layout of layoutNodes) {
        if (
          !layout.node.repo &&
          (layout.node.label.toLowerCase().includes(query) ||
            layout.node.fullLabel.toLowerCase().includes(query))
        ) {
          matchIds.add(layout.node.id)
        }
      }
    }
    const selectedNeighborIds = new Set<string>()
    if (selectedId) {
      selectedNeighborIds.add(selectedId)
      for (const edge of edges) {
        if (edge.source === selectedId) selectedNeighborIds.add(edge.target)
        if (edge.target === selectedId) selectedNeighborIds.add(edge.source)
      }
    }
    const rankedLabels = [...layoutNodes]
      .filter((layout) => !layout.node.repo)
      .sort((left, right) => right.degree - left.degree)
      .slice(0, 22)
      .map((layout) => layout.node.id)

    return {
      repositories,
      layoutNodes,
      nodeById,
      edges,
      relationKinds,
      matchIds,
      selectedNeighborIds,
      rankedLabelIds: new Set(rankedLabels),
    }
  }, [darkMode, data.edges, data.nodes, enabledKinds, hiddenRepoIds, query, selectedId])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(([entry]) => {
      setSize({
        width: Math.max(1, entry.contentRect.width),
        height: Math.max(1, entry.contentRect.height),
      })
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || size.width === 0 || size.height === 0) return
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.round(size.width * pixelRatio)
    canvas.height = Math.round(size.height * pixelRatio)
    canvas.style.width = `${size.width}px`
    canvas.style.height = `${size.height}px`
    const context = canvas.getContext('2d')
    if (!context) return
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
    const rootStyles = getComputedStyle(document.documentElement)
    const graphBackground = rootStyles.getPropertyValue('--terminal-bg').trim() || (darkMode ? '#151514' : '#f4f6fa')
    context.fillStyle = graphBackground
    context.fillRect(0, 0, size.width, size.height)

    const fitScale = Math.min(size.width, size.height) / WORLD_SIZE
    const worldScale = fitScale * view.scale
    context.save()
    context.translate(size.width / 2 + view.panX, size.height / 2 + view.panY)
    context.scale(worldScale, worldScale)

    const worldRadius = WORLD_SIZE / 2
    for (let ring = 1; ring <= 4; ring++) {
      context.beginPath()
      context.arc(0, 0, (worldRadius / 4.8) * ring, 0, Math.PI * 2)
      context.strokeStyle = darkMode ? 'rgba(154,160,191,0.07)' : 'rgba(76,102,214,0.11)'
      context.lineWidth = 1 / worldScale
      context.stroke()
    }

    for (const edge of graph.edges) {
      const source = graph.nodeById.get(edge.source)
      const target = graph.nodeById.get(edge.target)
      if (!source || !target) continue
      const selected = Boolean(
        selectedId && (edge.source === selectedId || edge.target === selectedId),
      )
      const matched = query && (graph.matchIds.has(edge.source) || graph.matchIds.has(edge.target))
      const dimmedBySelection = selectedId && !selected
      const dimmedBySearch = query && !matched
      const baseAlpha = edge.crossRepo ? (darkMode ? 0.28 : 0.34) : (darkMode ? 0.095 : 0.15)
      const alpha = selected
        ? 0.82
        : matched
          ? 0.48
          : dimmedBySelection || dimmedBySearch
            ? darkMode ? 0.012 : 0.025
            : baseAlpha
      if (alpha < 0.01) continue
      const midpointX = (source.x + target.x) / 2
      const midpointY = (source.y + target.y) / 2
      const curve = edge.crossRepo ? 0.13 : 0.045
      context.beginPath()
      context.moveTo(source.x, source.y)
      context.quadraticCurveTo(
        midpointX - midpointY * curve,
        midpointY + midpointX * curve,
        target.x,
        target.y,
      )
      context.strokeStyle = colorForEdge(edge, darkMode)
      context.globalAlpha = alpha
      context.lineWidth = selected ? 2.2 : edge.crossRepo ? 1.15 : 0.6
      if (selected) {
        context.shadowColor = colorForEdge(edge, darkMode)
        context.shadowBlur = 8
      }
      context.stroke()
      context.shadowBlur = 0
      context.globalAlpha = 1
    }

    const hovered = hoveredId ? graph.nodeById.get(hoveredId) : null
    const labels: LayoutNode[] = []
    for (const layout of graph.layoutNodes) {
      const selected = layout.node.id === selectedId
      const matched = graph.matchIds.has(layout.node.id)
      const neighbor = graph.selectedNeighborIds.has(layout.node.id)
      const hoveredNode = layout.node.id === hoveredId
      const dimmed = (selectedId && !neighbor && !layout.node.repo) || (query && !matched && !layout.node.repo)
      const radius = layout.radius * (selected || hoveredNode ? 1.75 : matched ? 1.45 : 1)
      context.save()
      context.globalAlpha = dimmed ? 0.09 : 1
      drawShape(context, layout, radius)
      context.fillStyle = layout.color
      if (layout.node.repo || selected || matched || hoveredNode || layout.degree >= 12) {
        context.shadowColor = layout.color
        context.shadowBlur = layout.node.repo ? 24 : selected || matched ? 18 : 8
      }
      context.fill()
      context.shadowBlur = 0
      if (layout.node.repo) {
        context.lineWidth = 2.5
        context.strokeStyle = '#f8fafc'
        context.globalAlpha = 0.7
        context.stroke()
        context.beginPath()
        context.arc(layout.x, layout.y, radius * 0.45, 0, Math.PI * 2)
        context.fillStyle = graphBackground
        context.fill()
      }
      if (selected || matched) {
        drawShape(context, layout, radius + 4)
        context.lineWidth = 1.5
        context.strokeStyle = selected ? (darkMode ? '#ffffff' : '#111827') : (darkMode ? '#facc15' : '#ca8a04')
        context.stroke()
      }
      context.restore()
      if (
        layout.node.repo ||
        selected ||
        matched ||
        hoveredNode ||
        (view.scale >= 1.35 && graph.rankedLabelIds.has(layout.node.id))
      ) {
        labels.push(layout)
      }
    }

    for (const layout of labels) {
      const prominent = layout.node.repo || layout.node.id === selectedId || layout.node.id === hoveredId
      const label = shortLabel(layout.node.label)
      context.font = `${prominent ? 600 : 500} ${prominent ? 12 : 9.5}px JetBrains Mono, monospace`
      const width = context.measureText(label).width + 14
      const x = layout.x - width / 2
      const y = layout.y + layout.radius + 8
      context.fillStyle = darkMode
        ? prominent ? 'rgba(24,24,23,0.96)' : 'rgba(24,24,23,0.82)'
        : prominent ? 'rgba(255,255,255,0.96)' : 'rgba(255,255,255,0.86)'
      context.strokeStyle = layout.color
      context.lineWidth = prominent ? 1 : 0.6
      context.beginPath()
      context.roundRect(x, y, width, prominent ? 24 : 19, 4)
      context.fill()
      context.stroke()
      context.fillStyle = darkMode ? '#f3f2ef' : '#171a21'
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(label, layout.x, y + (prominent ? 12 : 9.5))
    }

    if (hovered && !labels.some((layout) => layout.node.id === hovered.node.id)) {
      // Kept for defensive completeness when label LOD rules change.
      context.fillStyle = '#f8fafc'
      context.fillText(shortLabel(hovered.node.label), hovered.x, hovered.y)
    }
    context.restore()
  }, [darkMode, graph, hoveredId, query, selectedId, size, view])

  const screenToWorld = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const fitScale = Math.min(size.width, size.height) / WORLD_SIZE
    const worldScale = fitScale * view.scale
    return {
      x: (clientX - rect.left - size.width / 2 - view.panX) / worldScale,
      y: (clientY - rect.top - size.height / 2 - view.panY) / worldScale,
    }
  }

  const nodeAt = (clientX: number, clientY: number): LayoutNode | null => {
    const point = screenToWorld(clientX, clientY)
    const fitScale = Math.min(size.width, size.height) / WORLD_SIZE
    const hitPadding = 7 / Math.max(0.1, fitScale * view.scale)
    let best: LayoutNode | null = null
    let distance = Number.POSITIVE_INFINITY
    for (const layout of graph.layoutNodes) {
      const current = Math.hypot(layout.x - point.x, layout.y - point.y)
      if (current <= layout.radius + hitPadding && current < distance) {
        best = layout
        distance = current
      }
    }
    return best
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      panX: view.panX,
      panY: view.panY,
      moved: false,
    }
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current
    if (drag) {
      const deltaX = event.clientX - drag.x
      const deltaY = event.clientY - drag.y
      if (Math.abs(deltaX) + Math.abs(deltaY) > 3) drag.moved = true
      if (drag.moved) {
        setView((current) => ({
          ...current,
          panX: drag.panX + deltaX,
          panY: drag.panY + deltaY,
        }))
        return
      }
    }
    setHoveredId(nodeAt(event.clientX, event.clientY)?.node.id ?? null)
  }

  const onPointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current
    dragRef.current = null
    if (!drag?.moved) onSelect(nodeAt(event.clientX, event.clientY)?.node.id ?? null)
  }

  const onWheel = (event: ReactWheelEvent<HTMLCanvasElement>) => {
    event.preventDefault()
    const factor = event.deltaY < 0 ? 1.12 : 0.89
    setView((current) => ({
      ...current,
      scale: Math.min(3.2, Math.max(0.55, current.scale * factor)),
    }))
  }

  const resetView = () => setView({ scale: 1, panX: 0, panY: 0 })
  const toggleKind = (kind: string) => {
    setEnabledKinds((previous) => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  return (
    <div ref={containerRef} className={cn('relative h-full min-h-0 overflow-hidden bg-(--terminal-bg)', className)}>
      <canvas
        ref={canvasRef}
        aria-label="Interactive code constellation"
        className={cn('absolute inset-0 touch-none cursor-grab active:cursor-grabbing', hoveredId && 'cursor-pointer')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          dragRef.current = null
          setHoveredId(null)
        }}
        onWheel={onWheel}
      />

      <div className="pointer-events-none absolute left-3 top-3 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-1.5">
        <div className="pointer-events-auto flex items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-card)/85 px-2.5 py-1.5 text-[9px] text-(--color-text-muted) shadow-lg backdrop-blur-md">
          <span className="h-1.5 w-1.5 rounded-full bg-(--accent-purple) shadow-[0_0_8px_currentColor]" />
          {selectedId ? 'Focused neighborhood' : query ? `${graph.matchIds.size} matches` : 'Code constellation'}
          <span className="text-(--color-border-strong)">|</span>
          <span className="font-mono text-(--color-text)">{graph.layoutNodes.length.toLocaleString(getIntlLocale())} nodes</span>
          <span className="font-mono text-(--color-text-subtle)">{graph.edges.length.toLocaleString(getIntlLocale())} edges</span>
        </div>
        <div className="pointer-events-auto flex flex-wrap items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-card)/85 p-1 shadow-lg backdrop-blur-md">
          <button
            type="button"
            onClick={() => setEnabledKinds(new Set())}
            className={cn(
              'rounded px-2 py-1 text-[9px] font-medium transition-colors',
              enabledKinds.size === 0 ? 'bg-(--bg-hover) text-(--color-text)' : 'text-(--color-text-subtle) hover:text-(--color-text)',
            )}
          >
            All
          </button>
          {graph.relationKinds.map(([kind, count]) => {
            const active = enabledKinds.has(kind)
            return (
              <button
                key={kind}
                type="button"
                onClick={() => toggleKind(kind)}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-[9px] transition-colors',
                  active ? 'bg-(--bg-hover) text-(--color-text)' : 'text-(--color-text-subtle) hover:text-(--color-text)',
                )}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: (darkMode ? EDGE_COLORS : LIGHT_EDGE_COLORS)[kind] ?? '#64748b' }} />
                {kind} <span className="font-mono opacity-55">{count}</span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-card)/85 px-2.5 py-1.5 text-[9px] text-(--color-text-muted) shadow-lg backdrop-blur-md">
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-sm bg-rose-500" /> class</span>
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-fuchsia-500" /> function</span>
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rotate-45 bg-yellow-400" /> module</span>
        <span className="hidden text-(--color-text-subtle) lg:inline">drag to move · scroll to zoom</span>
      </div>

      <div className="absolute bottom-3 right-3 flex items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-card)/90 p-1 text-(--color-text-muted) shadow-lg backdrop-blur-md">
        <button type="button" aria-label="Zoom out" onClick={() => setView((current) => ({ ...current, scale: Math.max(0.55, current.scale * 0.85) }))} className="flex h-7 w-7 items-center justify-center rounded hover:bg-(--bg-hover) hover:text-(--color-text)"><Minus size={13} /></button>
        <span className="w-10 text-center font-mono text-[9px] text-(--color-text-subtle)">{Math.round(view.scale * 100)}%</span>
        <button type="button" aria-label="Zoom in" onClick={() => setView((current) => ({ ...current, scale: Math.min(3.2, current.scale * 1.15) }))} className="flex h-7 w-7 items-center justify-center rounded hover:bg-(--bg-hover) hover:text-(--color-text)"><Plus size={13} /></button>
        <button type="button" aria-label="Reset view" onClick={resetView} className="flex h-7 w-7 items-center justify-center rounded hover:bg-(--bg-hover) hover:text-(--color-text)"><RotateCcw size={12} /></button>
        {selectedId && (
          <button type="button" aria-label="Clear focus" onClick={() => onSelect(null)} className="flex h-7 w-7 items-center justify-center rounded text-cyan-400 hover:bg-white/10"><Focus size={12} /></button>
        )}
      </div>
    </div>
  )
}
