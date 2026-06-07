import { create } from 'zustand'
import type { Node, Edge } from 'reactflow'
import type { NodeData } from '../types/workflow'

interface HistoryEntry {
  nodes: Node<NodeData>[]
  edges: Edge[]
}

interface WorkflowState {
  workflowId: string | null
  workflowName: string
  workflowDescription: string
  nodes: Node<NodeData>[]
  edges: Edge[]
  selectedNodeId: string | null
  isRunning: boolean

  // Undo/Redo
  history: HistoryEntry[]
  historyIndex: number
  canUndo: boolean
  canRedo: boolean

  setWorkflowId: (id: string | null) => void
  setWorkflowName: (name: string) => void
  setWorkflowDescription: (desc: string) => void
  setNodes: (nodes: Node<NodeData>[]) => void
  setEdges: (edges: Edge[]) => void
  addNode: (node: Node<NodeData>) => void
  removeNode: (nodeId: string) => void
  updateNodeData: (nodeId: string, data: Partial<NodeData>) => void
  setSelectedNodeId: (id: string | null) => void
  setIsRunning: (running: boolean) => void
  resetWorkflow: () => void
  loadWorkflow: (id: string, name: string, description: string, nodes: Node<NodeData>[], edges: Edge[]) => void
  undo: () => void
  redo: () => void
  pushHistory: () => void
}

const MAX_HISTORY = 50

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  workflowId: null,
  workflowName: 'Untitled Workflow',
  workflowDescription: '',
  nodes: [],
  edges: [],
  selectedNodeId: null,
  isRunning: false,
  history: [],
  historyIndex: -1,
  canUndo: false,
  canRedo: false,

  setWorkflowId: (id) => set({ workflowId: id }),
  setWorkflowName: (name) => set({ workflowName: name }),
  setWorkflowDescription: (desc) => set({ workflowDescription: desc }),

  setNodes: (nodes) => {
    get().pushHistory()
    set({ nodes })
  },

  setEdges: (edges) => {
    get().pushHistory()
    set({ edges })
  },

  addNode: (node) => {
    get().pushHistory()
    set((state) => ({ nodes: [...state.nodes, node] }))
  },

  removeNode: (nodeId) => {
    get().pushHistory()
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== nodeId),
      edges: state.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
      selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId
    }))
  },

  updateNodeData: (nodeId, data) => {
    get().pushHistory()
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n
      )
    }))
  },

  setSelectedNodeId: (id) => set({ selectedNodeId: id }),
  setIsRunning: (running) => set({ isRunning: running }),

  resetWorkflow: () => {
    get().pushHistory()
    set({
      workflowId: null,
      workflowName: 'Untitled Workflow',
      workflowDescription: '',
      nodes: [],
      edges: [],
      selectedNodeId: null,
      isRunning: false
    })
  },

  loadWorkflow: (id, name, description, nodes, edges) =>
    set({
      workflowId: id,
      workflowName: name,
      workflowDescription: description,
      nodes,
      edges,
      selectedNodeId: null,
      isRunning: false,
      history: [],
      historyIndex: -1,
      canUndo: false,
      canRedo: false
    }),

  pushHistory: () => {
    const { nodes, edges, history, historyIndex } = get()
    const entry: HistoryEntry = { nodes: [...nodes], edges: [...edges] }
    const newHistory = history.slice(0, historyIndex + 1)
    newHistory.push(entry)
    if (newHistory.length > MAX_HISTORY) newHistory.shift()
    set({
      history: newHistory,
      historyIndex: newHistory.length - 1,
      canUndo: newHistory.length > 1,
      canRedo: false
    })
  },

  undo: () => {
    const { history, historyIndex } = get()
    if (historyIndex <= 0) return
    const newIndex = historyIndex - 1
    const entry = history[newIndex]
    set({
      nodes: [...entry.nodes],
      edges: [...entry.edges],
      historyIndex: newIndex,
      canUndo: newIndex > 0,
      canRedo: true
    })
  },

  redo: () => {
    const { history, historyIndex } = get()
    if (historyIndex >= history.length - 1) return
    const newIndex = historyIndex + 1
    const entry = history[newIndex]
    set({
      nodes: [...entry.nodes],
      edges: [...entry.edges],
      historyIndex: newIndex,
      canUndo: true,
      canRedo: newIndex < history.length - 1
    })
  }
}))
