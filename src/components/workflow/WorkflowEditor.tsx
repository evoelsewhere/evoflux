import { useCallback, useState, useRef, useEffect, useMemo } from 'react'
import ReactFlow, {
  addEdge, Background, Controls, MiniMap,
  BackgroundVariant, ReactFlowProvider,
  useNodesState, useEdgesState,
  useReactFlow,
  type Connection, type NodeTypes, type EdgeTypes
} from 'reactflow'
import 'reactflow/dist/style.css'
import { Input, message, Spin } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { nanoid } from 'nanoid'
import { autoLayout } from '../../utils/layout'
import BaseNode from './nodes/_base/BaseNode'
import CommentNode from './nodes/CommentNode'
import CustomEdge from './edges/CustomEdge'
import Sidebar from '../layout/Sidebar'
import NodePopup from './NodePopup'
import EdgePopup from './EdgePopup'
import RunPanel, { type RunEvent } from './RunPanel'
import RunInputDialog from './RunInputDialog'
import AssistantPanel from './AssistantPanel'
import CodeEditor from '../common/CodeEditor'
import ErrorBoundary from '../common/ErrorBoundary'
import type { WorkflowToolContext } from '../../assistant/tools'
import type { NodeDefinition } from './registry'
import type { NodeData } from '../../types/workflow'
import type { Node, Edge } from 'reactflow'

const nodeTypes: NodeTypes = { default: BaseNode, comment: CommentNode }
const edgeTypes: EdgeTypes = { custom: CustomEdge }
const proOptions = { hideAttribution: true }

const DEFAULT_START: Node<NodeData> = {
  id: 'start-1', type: 'default', position: { x: 250, y: 50 },
  data: { label: 'Start', type: 'manual-trigger', icon: 'play-circle', category: 'trigger', config: { variables: [] } }
}

interface HistoryEntry { nodes: Node<NodeData>[]; edges: Edge[] }
const MAX_HISTORY = 50

function EditorCanvas() {
  const { screenToFlowPosition, fitView, getNodes, getEdges } = useReactFlow()

  const [nodes, setNodes, onNodesChange] = useNodesState([DEFAULT_START])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [workflowName, setWorkflowName] = useState('Untitled Workflow')
  const [workflowDescription] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyIndex, setHistoryIndex] = useState(-1)
  const canUndo = historyIndex > 0
  const canRedo = historyIndex < history.length - 1

  const [showCode, setShowCode] = useState(false)
  const [showRun, setShowRun] = useState(false)
  const [showInput, setShowInput] = useState(false)
  const [showAssistant, setShowAssistant] = useState(false)
  const [layoutDirection, setLayoutDirection] = useState<'TB' | 'LR'>('TB')
  const [runEvents, setRunEvents] = useState<RunEvent[]>([])
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, 'idle' | 'running' | 'completed' | 'error'>>({})
  const [edgeStatuses, setEdgeStatuses] = useState<Record<string, 'idle' | 'active' | 'completed' | 'error'>>({})
  const [edgeIterations, setEdgeIterations] = useState<Record<string, number>>({})
  const [nodeOutputs, setNodeOutputs] = useState<Record<string, unknown>>({})
  const [elapsed, setElapsed] = useState(0)
  const [editingName, setEditingName] = useState(false)
  const [popupNode, setPopupNode] = useState<Node<NodeData> | null>(null)
  const [popupEdge, setPopupEdge] = useState<Edge | null>(null)
  const [loading, setLoading] = useState(true)
  const [showSearch, setShowSearch] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [showVarViewer, setShowVarViewer] = useState(false)
  const [monH, setMonH] = useState(300)
  const clipboardRef = useRef<{ nodes: Node<NodeData>[]; edges: Edge[] } | null>(null)

  const navigate = useNavigate()
  const { id } = useParams()
  const wrapperRef = useRef<HTMLDivElement>(null)
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const elapsedTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const runStartRef = useRef<number>(0)
  const eventCleanupRef = useRef<(() => void) | null>(null)
  const latestName = useRef(workflowName)
  const latestDesc = useRef(workflowDescription)
  const latestId = useRef(id)

  latestName.current = workflowName
  latestDesc.current = workflowDescription
  latestId.current = id

  const pushHistory = useCallback(() => {
    setHistory(prev => {
      const idx = historyIndex
      const entry: HistoryEntry = { nodes: [...nodes], edges: [...edges] }
      const newHist = prev.slice(0, idx + 1)
      newHist.push(entry)
      if (newHist.length > MAX_HISTORY) newHist.shift()
      setHistoryIndex(newHist.length - 1)
      return newHist
    })
  }, [nodes, edges, historyIndex])

  const doSave = useCallback(async (ns: Node<NodeData>[], es: Edge[], wfName: string, wfDesc: string, wfId?: string) => {
    try { await window.api.workflow.save({ id: wfId, name: wfName, description: wfDesc, nodes: ns, edges: es }) } catch { /* */ }
  }, [])

  const doSaveSync = useCallback(() => {
    const ns = getNodes() as Node<NodeData>[]
    const es = getEdges()
    const wfName = latestName.current
    const wfDesc = latestDesc.current
    const wfId = latestId.current
    if (!wfId || ns.length === 0) return
    try { window.api.workflow.saveSync({ id: wfId, name: wfName, description: wfDesc, nodes: ns, edges: es }) } catch { /* */ }
  }, [getNodes, getEdges])

  useEffect(() => {
    if (!id) { setLoading(false); return }
    let cancelled = false
    ;(async () => {
      try {
        const wf = await window.api.workflow.load(id) as { id: string; name: string; description: string; nodes: Node<NodeData>[]; edges: Edge[] } | null
        if (cancelled) return
        if (wf && wf.nodes && wf.nodes.length > 0) {
          setNodes(wf.nodes); setEdges(wf.edges || [])
          setWorkflowName(wf.name)
          setHistory([{ nodes: wf.nodes, edges: wf.edges || [] }])
          setHistoryIndex(0)
          setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 100)
        } else {
          setNodes([DEFAULT_START]); setEdges([])
          setWorkflowName('Untitled Workflow')
          doSave([DEFAULT_START], [], 'Untitled Workflow', '', id)
        }
      } catch { if (!cancelled) { setNodes([DEFAULT_START]); setEdges([]) } }
      finally { if (!cancelled) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [id])

  useEffect(() => {
    if (nodes.length === 0 || loading) return
    if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current)
    autoSaveTimer.current = setTimeout(() => { doSave(nodes, edges, workflowName, workflowDescription, id) }, 500)
    return () => { if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current) }
  }, [nodes, edges, workflowName, loading])

  useEffect(() => {
    const handleBeforeUnload = () => { doSaveSync() }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current)
      doSaveSync()
    }
  }, [id, doSaveSync])

  const updateNodeData = useCallback((nodeId: string, data: Partial<NodeData>) => {
    pushHistory()
    setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n))
  }, [setNodes, pushHistory])

  const handleDeleteNode = useCallback((nodeId: string) => {
    pushHistory()
    setNodes(prev => prev.filter(n => n.id !== nodeId))
    setEdges(prev => prev.filter(e => e.source !== nodeId && e.target !== nodeId))
    setSelectedNodeId(prev => prev === nodeId ? null : prev)
    setPopupNode(null)
  }, [setNodes, setEdges, pushHistory])

  const handleDeleteSelected = useCallback(() => {
    const selected = nodes.filter(n => n.selected)
    if (selected.length === 0) return
    pushHistory()
    const ids = new Set(selected.map(n => n.id))
    setNodes(prev => prev.filter(n => !ids.has(n.id)))
    setEdges(prev => prev.filter(e => !ids.has(e.source) && !ids.has(e.target)))
    setPopupNode(null)
  }, [nodes, setNodes, setEdges, pushHistory])

  const handleCopy = useCallback(() => {
    const selected = nodes.filter(n => n.selected || n.id === selectedNodeId)
    if (selected.length === 0) return
    const ids = new Set(selected.map(n => n.id))
    const relatedEdges = edges.filter(e => ids.has(e.source) && ids.has(e.target))
    clipboardRef.current = { nodes: selected, edges: relatedEdges }
    message.success(`Copied ${selected.length} node${selected.length > 1 ? 's' : ''}`)
  }, [nodes, edges, selectedNodeId])

  const handlePaste = useCallback(() => {
    const clip = clipboardRef.current
    if (!clip || clip.nodes.length === 0) return
    pushHistory()
    const idMap = new Map<string, string>()
    const offset = 40
    const newNodes = clip.nodes.map(n => {
      const newId = `${n.data.type}-${nanoid(6)}`
      idMap.set(n.id, newId)
      return { ...n, id: newId, position: { x: n.position.x + offset, y: n.position.y + offset }, selected: false }
    })
    const newEdges = clip.edges.map(e => ({
      ...e, id: `e-${idMap.get(e.source)}-${idMap.get(e.target)}-${nanoid(4)}`,
      source: idMap.get(e.source)!, target: idMap.get(e.target)!
    }))
    setNodes(prev => [...prev, ...newNodes as Node<NodeData>[]])
    setEdges(prev => [...prev, ...newEdges])
    clipboardRef.current = { nodes: newNodes as Node<NodeData>[], edges: newEdges }
    message.success(`Pasted ${newNodes.length} node${newNodes.length > 1 ? 's' : ''}`)
  }, [setNodes, setEdges, pushHistory])

  const handleUndo = useCallback(() => {
    if (!canUndo) return
    const newIndex = historyIndex - 1
    const entry = history[newIndex]
    setNodes([...entry.nodes]); setEdges([...entry.edges])
    setHistoryIndex(newIndex)
  }, [canUndo, historyIndex, history, setNodes, setEdges])

  const handleRedo = useCallback(() => {
    if (!canRedo) return
    const newIndex = historyIndex + 1
    const entry = history[newIndex]
    setNodes([...entry.nodes]); setEdges([...entry.edges])
    setHistoryIndex(newIndex)
  }, [canRedo, historyIndex, history, setNodes, setEdges])

  const edgesWithStatus = useMemo(() => {
    const hasNodeStatuses = Object.keys(nodeStatuses).length > 0
    const hasEdgeStatuses = Object.keys(edgeStatuses).length > 0
    if (!hasNodeStatuses && !hasEdgeStatuses) return edges
    return edges.map(edge => {
      const explicitEdgeStatus = edgeStatuses[edge.id]
      let edgeStatus: 'idle' | 'active' | 'completed' | 'error' = explicitEdgeStatus || 'idle'
      if (!explicitEdgeStatus && hasNodeStatuses) {
        const sourceStatus = nodeStatuses[edge.source] || 'idle'
        const targetStatus = nodeStatuses[edge.target] || 'idle'
        if (targetStatus === 'error' || sourceStatus === 'error') edgeStatus = 'error'
        else if (sourceStatus === 'completed' && targetStatus === 'running') edgeStatus = 'active'
        else if (sourceStatus === 'completed' && targetStatus === 'completed') edgeStatus = 'completed'
        else if (sourceStatus === 'running') edgeStatus = 'active'
      }
      const iteration = edgeIterations[edge.id]
      return { ...edge, data: { ...edge.data, status: edgeStatus, isBackEdge: edge.data?.isBackEdge || false, condition: edge.data?.condition, maxIterations: edge.data?.maxIterations, iteration } }
    })
  }, [edges, nodeStatuses, edgeStatuses, edgeIterations])

  const updateNodeStatus = useCallback((nodeId: string, status: 'idle' | 'running' | 'completed' | 'error', output?: unknown) => {
    setNodeStatuses(prev => ({ ...prev, [nodeId]: status }))
    if (output !== undefined) setNodeOutputs(prev => ({ ...prev, [nodeId]: output }))
    setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, data: { ...n.data, status, error: status === 'error' ? String(output) : undefined } } : n))
  }, [setNodes])

  const handleRunWithInputs = useCallback(async (inputs: Record<string, unknown>) => {
    setShowInput(false); setShowRun(true); setRunEvents([]); setIsRunning(true)
    setNodeStatuses({}); setNodeOutputs({}); setEdgeStatuses({}); setEdgeIterations({}); setElapsed(0)
    setNodes(prev => prev.map(n => ({ ...n, data: { ...n.data, status: 'idle' as const, error: undefined } })))
    runStartRef.current = Date.now()
    elapsedTimer.current = setInterval(() => { setElapsed(Date.now() - runStartRef.current) }, 100)

    const cleanup = window.api.workflow.onEvent((event: unknown) => {
      const ev = event as RunEvent
      setRunEvents(prev => [...prev, ev])
      if (ev.type === 'node:start' && ev.nodeId) updateNodeStatus(ev.nodeId, 'running')
      else if (ev.type === 'node:complete' && ev.nodeId) updateNodeStatus(ev.nodeId, 'completed', ev.output)
      else if (ev.type === 'node:error' && ev.nodeId) updateNodeStatus(ev.nodeId, 'error', ev.error)
      else if (ev.type === 'edge:activate' && ev.edgeId) {
        setEdgeStatuses(prev => ({ ...prev, [ev.edgeId!]: 'active' }))
        if (ev.iteration) setEdgeIterations(prev => ({ ...prev, [ev.edgeId!]: ev.iteration! }))
      } else if (ev.type === 'edge:skip' && ev.edgeId) setEdgeStatuses(prev => ({ ...prev, [ev.edgeId!]: 'idle' }))
      else if (ev.type === 'graph:complete') { setIsRunning(false); if (elapsedTimer.current) clearInterval(elapsedTimer.current); setElapsed(Date.now() - runStartRef.current) }
      else if (ev.type === 'graph:aborted' || ev.type === 'graph:error') { setIsRunning(false); if (elapsedTimer.current) clearInterval(elapsedTimer.current) }
    })
    eventCleanupRef.current = cleanup

    try {
      const dsl = {
        graph: {
          nodes: nodes.map(n => ({ id: n.id, type: n.data.type, data: n.data, position: n.position })),
          edges: edges.map(e => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle, condition: e.data?.condition, isBackEdge: e.data?.isBackEdge, maxIterations: e.data?.maxIterations }))
        }
      }
      await window.api.workflow.run(dsl, { inputs, maxSteps: 1000, maxTimeMs: 600000 })
    } catch (err) {
      setRunEvents(prev => [...prev, { type: 'graph:error', timestamp: Date.now(), error: err instanceof Error ? err : new Error(String(err)) }])
    } finally {
      setIsRunning(false)
      if (elapsedTimer.current) clearInterval(elapsedTimer.current)
    }
  }, [nodes, edges, workflowName, setIsRunning, updateNodeStatus])

  const hasInputVariables = nodes.some(n => n.data.type === 'manual-trigger' && Array.isArray(n.data.config?.variables) && (n.data.config?.variables as unknown[])?.length > 0)
  const handleRun = useCallback(() => { if (hasInputVariables) setShowInput(true); else handleRunWithInputs({}) }, [hasInputVariables, handleRunWithInputs])
  const handleStop = useCallback(() => { window.api.workflow.stop(); setIsRunning(false); if (elapsedTimer.current) clearInterval(elapsedTimer.current); setRunEvents(prev => [...prev, { type: 'graph:aborted', timestamp: Date.now() }]) }, [])

  useEffect(() => { return () => { if (elapsedTimer.current) clearInterval(elapsedTimer.current); if (eventCleanupRef.current) eventCleanupRef.current() } }, [])

  const resizeMon = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const startY = e.clientY; const startH = monH
    const onMove = (ev: MouseEvent) => { setMonH(Math.min(500, Math.max(200, startH + startY - ev.clientY))) }
    const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp)
  }, [monH])

  const onConnect = useCallback((p: Connection) => setEdges(es => addEdge({ ...p, type: 'custom', animated: true }, es)), [setEdges])
  const onNodeClick = useCallback((_: React.MouseEvent, n: Node) => {
    if (n.type === 'comment') return
    setSelectedNodeId(n.id); setPopupNode(n as Node<NodeData>); setPopupEdge(null)
  }, [])
  const onEdgeClick = useCallback((_: React.MouseEvent, e: Edge) => { setPopupEdge(e); setPopupNode(null) }, [])
  const onPaneClick = useCallback(() => { setSelectedNodeId(null); setPopupNode(null); setPopupEdge(null) }, [])

  const handleEdgeUpdate = useCallback((edgeId: string, data: Record<string, unknown>) => {
    setEdges(prev => prev.map(e => e.id === edgeId ? { ...e, data: { ...e.data, ...data }, label: data.label !== undefined ? String(data.label) : e.label } as Edge : e))
  }, [setEdges])

  const handleEdgeDelete = useCallback((edgeId: string) => {
    setEdges(prev => prev.filter(e => e.id !== edgeId))
    setPopupEdge(null)
  }, [setEdges])

  const addNode = useCallback((type: string, def: NodeDefinition, position?: { x: number; y: number }) => {
    const nid = `${type}-${nanoid(6)}`
    const data = type === 'comment' ? { label: 'Comment', type: 'comment', text: 'Double-click to edit...', direction: layoutDirection } : { label: def.label, type, icon: def.icon, category: def.category, config: {}, direction: layoutDirection }
    const pos = position || { x: 200 + Math.random() * 300, y: 80 + Math.random() * 300 }
    const n = { id: nid, type: type === 'comment' ? 'comment' : 'default', position: pos, data }
    setNodes(prev => [...prev, n as Node<NodeData>])
  }, [setNodes, layoutDirection])

  const onDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }, [])
  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/reactflow-type')
    const defStr = e.dataTransfer.getData('application/reactflow-def')
    if (!type || !defStr) return
    const def = JSON.parse(defStr) as NodeDefinition
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY })

    const insertedNode = { id: `${type}-${nanoid(6)}`, type: type === 'comment' ? 'comment' : 'default', position: pos, data: type === 'comment' ? { label: 'Comment', type: 'comment', text: 'Double-click to edit...', direction: layoutDirection } : { label: def.label, type, icon: def.icon, category: def.category, config: {}, direction: layoutDirection } }

    const nearbyEdge = edges.find(edge => {
      const src = nodes.find(n => n.id === edge.source)
      const tgt = nodes.find(n => n.id === edge.target)
      if (!src || !tgt) return false
      const midX = (src.position.x + tgt.position.x) / 2
      const midY = (src.position.y + tgt.position.y) / 2
      const dx = pos.x - midX; const dy = pos.y - midY
      return Math.sqrt(dx * dx + dy * dy) < 120
    })

    if (nearbyEdge) {
      pushHistory()
      setNodes(prev => [...prev, insertedNode as Node<NodeData>])
      setEdges(prev => [
        ...prev.filter(e => e.id !== nearbyEdge.id),
        { id: `e-${nearbyEdge.source}-${insertedNode.id}-${nanoid(4)}`, source: nearbyEdge.source, target: insertedNode.id, type: 'custom', animated: true, sourceHandle: nearbyEdge.sourceHandle },
        { id: `e-${insertedNode.id}-${nearbyEdge.target}-${nanoid(4)}`, source: insertedNode.id, target: nearbyEdge.target, type: 'custom', animated: true, targetHandle: nearbyEdge.targetHandle }
      ])
      message.success('Auto-connected between nodes')
    } else {
      addNode(type, def, pos)
    }
  }, [screenToFlowPosition, addNode, edges, nodes, layoutDirection, setNodes, setEdges, pushHistory])

  const handleSave = useCallback(async () => { await doSave(nodes, edges, workflowName, workflowDescription, id); message.success('Saved') }, [id, nodes, edges, workflowName, workflowDescription, doSave])
  const handleBack = useCallback(() => { doSaveSync(); navigate('/workflows') }, [doSaveSync, navigate])
  const applyDirection = useCallback((ns: Node<NodeData>[], dir: 'TB' | 'LR') => ns.map(n => ({ ...n, data: { ...n.data, direction: dir } })), [])
  const handleLayout = useCallback(() => { const l = applyDirection(autoLayout(nodes, edges, layoutDirection), layoutDirection); setNodes(l) }, [nodes, edges, layoutDirection, setNodes, applyDirection])
  const handleToggleLayout = useCallback(() => { const next = layoutDirection === 'TB' ? 'LR' : 'TB'; setLayoutDirection(next); setNodes(applyDirection(autoLayout(nodes, edges, next), next)) }, [layoutDirection, nodes, edges, setNodes, applyDirection])

  const handleExportImage = useCallback(async () => {
    const rfEl = document.querySelector('.react-flow') as HTMLElement | null
    if (!rfEl) return
    try {
      const svgEl = rfEl.querySelector('svg') as SVGSVGElement | null
      if (!svgEl) { message.error('No canvas found'); return }
      const svgData = new XMLSerializer().serializeToString(svgEl)
      const canvas = document.createElement('canvas')
      const rect = rfEl.getBoundingClientRect()
      canvas.width = rect.width * 2; canvas.height = rect.height * 2
      const ctx = canvas.getContext('2d')!
      ctx.scale(2, 2)
      ctx.fillStyle = '#000000'
      ctx.fillRect(0, 0, rect.width, rect.height)
      const img = new Image()
      img.onload = () => {
        ctx.drawImage(img, 0, 0, rect.width, rect.height)
        const link = document.createElement('a')
        link.download = `${workflowName || 'workflow'}.png`
        link.href = canvas.toDataURL('image/png')
        link.click()
        message.success('Exported as PNG')
      }
      img.onerror = () => message.error('Export failed')
      img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)))
    } catch { message.error('Export failed') }
  }, [workflowName])

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key === 's') { e.preventDefault(); handleSave() }
      if (mod && e.key === 'z' && !e.shiftKey) { e.preventDefault(); handleUndo() }
      if (mod && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); handleRedo() }
      if (mod && e.key === 'c') { e.preventDefault(); handleCopy() }
      if (mod && e.key === 'v') { e.preventDefault(); handlePaste() }
      if (mod && e.key === 'f') { e.preventDefault(); setShowSearch(true) }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (document.activeElement?.tagName === 'INPUT' || document.activeElement?.tagName === 'TEXTAREA') return
        e.preventDefault()
        const selected = nodes.filter(n => n.selected)
        if (selected.length > 1) handleDeleteSelected()
        else if (selectedNodeId) handleDeleteNode(selectedNodeId)
      }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [handleSave, handleUndo, handleRedo, selectedNodeId, handleDeleteNode, handleDeleteSelected, handleCopy, handlePaste, nodes])

  if (loading) {
    return <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)' }}><Spin size="large" /></div>
  }

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div className="titlebar-drag" style={{ height: 36, display: 'flex', alignItems: 'center', gap: 8, padding: '0 12px 0 72px', borderBottom: '1px solid var(--border-primary)', background: 'var(--bg-secondary)', flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Workflow</span>
          <div style={{ width: 1, height: 14, background: 'var(--border-primary)' }} />
          {editingName ? (
            <Input size="small" value={workflowName} onChange={(e) => setWorkflowName(e.target.value)} onBlur={() => setEditingName(false)} onPressEnter={() => setEditingName(false)} autoFocus style={{ width: 200, height: 24, fontSize: 12, fontWeight: 600, background: 'var(--bg-input)', borderColor: 'var(--border-secondary)', WebkitAppRegion: 'no-drag' } as React.CSSProperties} />
          ) : (
            <span onClick={() => setEditingName(true)} style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', cursor: 'pointer', padding: '1px 4px', borderRadius: 3, transition: 'background 0.1s', WebkitAppRegion: 'no-drag' } as React.CSSProperties}
              onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-hover)'} onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
              {workflowName}
            </span>
          )}
          {isRunning && (
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#60a5fa' }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#60a5fa', animation: 'pulse 1s infinite' }} />
              Running... {Math.round(elapsed / 1000)}s
            </div>
          )}
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div ref={wrapperRef} style={{ flex: 1, position: 'relative' }} onDragOver={onDragOver} onDrop={onDrop}>
            <ReactFlow
              nodes={nodes} edges={edgesWithStatus}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onNodeClick={onNodeClick} onEdgeClick={onEdgeClick} onPaneClick={onPaneClick}
              nodeTypes={nodeTypes} edgeTypes={edgeTypes} proOptions={proOptions}
              multiSelectionKeyCode="Shift" panOnDrag={[0, 1, 2]} panOnScroll zoomOnScroll={false} zoomOnPinch zoomOnDoubleClick={false}
              minZoom={0.15} maxZoom={3} fitView fitViewOptions={{ padding: 0.2 }}
              style={{ background: 'var(--bg-primary)' }} defaultEdgeOptions={{ type: 'custom', animated: true }}
            >
              <Background color="var(--border-primary)" gap={16} size={1} variant={BackgroundVariant.Dots} />
              <Controls />
              <MiniMap
                nodeColor={(n) => {
                  const d = n.data as NodeData
                  if (d.status === 'running') return '#60a5fa'
                  if (d.status === 'completed') return '#34d399'
                  if (d.status === 'error') return '#f87171'
                  switch (d.category) { case 'trigger': return '#34d399'; case 'ai': return '#60a5fa'; case 'logic': return '#fbbf24'; case 'tools': return '#2dd4bf'; case 'agent': return '#c084fc'; default: return '#444' }
                }}
                maskColor="rgba(0,0,0,0.6)" style={{ backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-primary)', borderRadius: 8 }}
              />
            </ReactFlow>
            {popupNode && <ErrorBoundary><NodePopup node={popupNode} onClose={() => setPopupNode(null)} onDelete={handleDeleteNode} onUpdateNodeData={updateNodeData} /></ErrorBoundary>}
            {popupEdge && <ErrorBoundary><EdgePopup edge={popupEdge} onClose={() => setPopupEdge(null)} onUpdate={handleEdgeUpdate} onDelete={handleEdgeDelete} /></ErrorBoundary>}

            {showSearch && (
              <div style={{
                position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
                display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
                background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
                borderRadius: 8, boxShadow: '0 8px 32px rgba(0,0,0,0.4)', zIndex: 500, minWidth: 280
              }}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4.5" stroke="var(--text-tertiary)" strokeWidth="1.3" /><path d="M9.5 9.5L13 13" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" /></svg>
                <input
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value)
                    const q = e.target.value.toLowerCase()
                    if (q) {
                      const match = nodes.find(n => n.data.label?.toLowerCase().includes(q) || n.data.type?.toLowerCase().includes(q))
                      if (match) { setSelectedNodeId(match.id); setNodes(prev => prev.map(n => ({ ...n, selected: n.id === match.id }))) }
                    }
                  }}
                  onKeyDown={(e) => { if (e.key === 'Escape') { setShowSearch(false); setSearchQuery('') } }}
                  placeholder="Search nodes..."
                  autoFocus
                  style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: 12, flex: 1 }}
                />
                {searchQuery && (
                  <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                    {nodes.filter(n => n.data.label?.toLowerCase().includes(searchQuery.toLowerCase()) || n.data.type?.toLowerCase().includes(searchQuery.toLowerCase())).length} found
                  </span>
                )}
                <button onClick={() => { setShowSearch(false); setSearchQuery('') }} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 14, padding: 0 }}>×</button>
              </div>
            )}

            {Object.keys(nodeOutputs).length > 0 && showVarViewer && (
              <div style={{
                position: 'absolute', top: 8, right: 8, width: 260, maxHeight: 300,
                background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
                borderRadius: 8, boxShadow: '0 8px 32px rgba(0,0,0,0.4)', zIndex: 500,
                display: 'flex', flexDirection: 'column', overflow: 'hidden'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', borderBottom: '1px solid var(--border-primary)' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>Variables</span>
                  <button onClick={() => setShowVarViewer(false)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 14, padding: 0 }}>×</button>
                </div>
                <div style={{ overflow: 'auto', padding: 8 }}>
                  {Object.entries(nodeOutputs).map(([nodeId, output]) => {
                    const node = nodes.find(n => n.id === nodeId)
                    return (
                      <div key={nodeId} style={{ marginBottom: 6 }}>
                        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--accent)', marginBottom: 2 }}>{node?.data.label || nodeId}</div>
                        <pre style={{ fontSize: 10, color: 'var(--text-secondary)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 60, overflow: 'auto', background: 'var(--bg-input)', padding: 4, borderRadius: 4 }}>
                          {typeof output === 'string' ? output.substring(0, 200) : JSON.stringify(output, null, 1)?.substring(0, 200)}
                        </pre>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {nodes.some(n => n.data.status === 'error') && (
              <div style={{
                position: 'absolute', bottom: 8, left: '50%', transform: 'translateX(-50%)',
                display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px',
                background: '#f8717120', border: '1px solid #f8717140',
                borderRadius: 8, zIndex: 500, cursor: 'pointer'
              }} onClick={() => {
                const errNode = nodes.find(n => n.data.status === 'error')
                if (errNode) { setSelectedNodeId(errNode.id); setPopupNode(errNode) }
              }}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" stroke="#f87171" strokeWidth="1.3" /><path d="M7 4V8M7 10V10.5" stroke="#f87171" strokeWidth="1.3" strokeLinecap="round" /></svg>
                <span style={{ fontSize: 11, color: '#f87171', fontWeight: 500 }}>
                  {nodes.filter(n => n.data.status === 'error').length} node{nodes.filter(n => n.data.status === 'error').length > 1 ? 's' : ''} with errors — click to inspect
                </span>
              </div>
            )}
          </div>

          {showRun && (
            <div style={{ height: monH, position: 'relative', borderTop: '1px solid var(--border-primary)' }}>
              <div className="resize-handle resize-handle-bottom" onMouseDown={resizeMon} />
              <RunPanel events={runEvents} nodes={nodes} nodeStatuses={nodeStatuses} nodeOutputs={nodeOutputs} isRunning={isRunning} elapsed={elapsed} onStop={handleStop} onClose={() => setShowRun(false)} onNodeClick={(nid) => { setSelectedNodeId(nid); const n = nodes.find(x => x.id === nid); if (n) setPopupNode(n) }} />
            </div>
          )}
        </div>
      </div>

      <Sidebar editorMode workflowName={workflowName} isRunning={isRunning} showCode={showCode} showAssistant={showAssistant} layoutDirection={layoutDirection} canUndo={canUndo} canRedo={canRedo}
        onSave={handleSave} onRun={handleRun} onStop={handleStop} onToggleCode={() => setShowCode(!showCode)} onToggleAssistant={() => setShowAssistant(!showAssistant)} onToggleLayout={handleToggleLayout}
        onUndo={canUndo ? handleUndo : undefined} onRedo={canRedo ? handleRedo : undefined} onAutoLayout={handleLayout} onBack={handleBack}
        onAddNode={addNode} />

      <RunInputDialog open={showInput} nodes={nodes} onRun={handleRunWithInputs} onCancel={() => setShowInput(false)} />

      {showAssistant && (
        <ErrorBoundary><AssistantPanel nodes={nodes} edges={edges} onClose={() => setShowAssistant(false)} onNodesChanged={() => {}}
          toolContext={{
            getNodes: () => nodes,
            getEdges: () => edges,
            addNode: (type, label, category, icon, config, position) => {
              const nid = `${type}-${nanoid(6)}`
              const pos = position || { x: 200 + Math.random() * 300, y: 80 + Math.random() * 300 }
              const n = { id: nid, type: 'default', position: pos, data: { label, type, icon, category, config } }
              setNodes(prev => [...prev, n as Node<NodeData>])
              return nid
            },
            updateNode: (nodeId, patch) => { updateNodeData(nodeId, patch) },
            deleteNode: (nodeId) => { handleDeleteNode(nodeId) },
            addEdge: (source, target, sourceHandle) => {
              setEdges(prev => [...prev, { id: `e-${source}-${target}-${nanoid(4)}`, source, target, sourceHandle, type: 'custom', animated: true }])
            },
            deleteEdge: (edgeId) => { setEdges(prev => prev.filter(e => e.id !== edgeId)) },
            autoLayout: () => { setNodes(autoLayout(nodes, edges)) },
            pushHistory: () => { pushHistory() }
          } as WorkflowToolContext} /></ErrorBoundary>
      )}

      {showCode && (
        <div style={{ width: 360, borderLeft: '1px solid var(--border-primary)' }}>
          <CodeEditor nodes={nodes} edges={edges} onApply={(n, e) => { setNodes(n); setEdges(e) }} />
        </div>
      )}
    </div>
  )
}

export default function WorkflowEditor() {
  return <ReactFlowProvider><EditorCanvas /></ReactFlowProvider>
}
