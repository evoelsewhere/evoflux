import type { AgentTool, ToolParameter } from '../engine/agent/tools'
import type { NodeData } from '../types/workflow'
import type { Node, Edge } from 'reactflow'

export interface WorkflowToolContext {
  getNodes: () => Node<NodeData>[]
  getEdges: () => Edge[]
  addNode: (type: string, label: string, category: string, icon: string, config: Record<string, unknown>, position?: { x: number; y: number }) => string
  updateNode: (nodeId: string, patch: Partial<NodeData>) => void
  deleteNode: (nodeId: string) => void
  addEdge: (source: string, target: string, sourceHandle?: string) => void
  deleteEdge: (edgeId: string) => void
  autoLayout: () => void
  pushHistory: () => void
}

function param(name: string, type: ToolParameter['type'], description: string, required = false): ToolParameter {
  return { name, type, description, required }
}

export function createWorkflowTools(ctx: WorkflowToolContext): AgentTool[] {
  return [
    {
      name: 'get_workflow',
      description: 'Get the current workflow state: all nodes with their configs and all edges. Use this first to understand what exists before making changes.',
      parameters: [],
      handler: 'custom',
      handlerFn: async () => {
        const nodes = ctx.getNodes().map(n => ({
          id: n.id, type: n.data.type, label: n.data.label, category: n.data.category, config: n.data.config
        }))
        const edges = ctx.getEdges().map(e => ({
          id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle
        }))
        return JSON.stringify({ nodes, edges }, null, 2)
      }
    },

    {
      name: 'list_node_types',
      description: 'List all available node types with their categories, descriptions, and default configs. Use this to know what node types exist before creating nodes.',
      parameters: [],
      handler: 'custom',
      handlerFn: async () => {
        const { NODE_CATEGORIES } = await import('../components/workflow/registry')
        const types = NODE_CATEGORIES.flatMap(cat =>
          cat.nodes.map(n => ({ type: n.type, label: n.label, category: n.category, description: n.description }))
        )
        return JSON.stringify(types, null, 2)
      }
    },

    {
      name: 'create_node',
      description: 'Create a new node on the canvas. Returns the new node ID. Use list_node_types first to see available types.',
      parameters: [
        param('type', 'string', 'Node type (e.g. llm, code, condition, template, shell, http-request)', true),
        param('label', 'string', 'Display label for the node', true),
        param('config', 'object', 'Node configuration object (model, prompt, code, etc.)', false),
        param('x', 'number', 'X position on canvas (auto-assigned if omitted)', false),
        param('y', 'number', 'Y position on canvas (auto-assigned if omitted)', false)
      ],
      handler: 'custom',
      handlerFn: async (args) => {
        const { NODE_CATEGORIES } = await import('../components/workflow/registry')
        const def = NODE_CATEGORIES.flatMap(c => c.nodes).find(n => n.type === args.type)
        if (!def) return `Error: Unknown node type '${args.type}'. Use list_node_types to see available types.`
        const position = args.x !== undefined && args.y !== undefined ? { x: Number(args.x), y: Number(args.y) } : undefined
        const nodeId = ctx.addNode(String(args.type), String(args.label || def.label), def.category, def.icon, (args.config as Record<string, unknown>) || {}, position)
        return `Created node '${nodeId}' (type: ${args.type}, label: ${args.label || def.label})`
      }
    },

    {
      name: 'update_node',
      description: 'Update an existing node\'s label or config. Only pass the fields you want to change.',
      parameters: [
        param('node_id', 'string', 'ID of the node to update', true),
        param('label', 'string', 'New label (optional)', false),
        param('config', 'object', 'New config fields to merge (optional)', false)
      ],
      handler: 'custom',
      handlerFn: async (args) => {
        const nodeId = String(args.node_id)
        const node = ctx.getNodes().find(n => n.id === nodeId)
        if (!node) return `Error: Node '${nodeId}' not found`
        const patch: Partial<NodeData> = {}
        if (args.label) patch.label = String(args.label)
        if (args.config && typeof args.config === 'object') {
          patch.config = { ...node.data.config, ...(args.config as Record<string, unknown>) }
        }
        ctx.updateNode(nodeId, patch)
        return `Updated node '${nodeId}'`
      }
    },

    {
      name: 'delete_node',
      description: 'Delete a node and all its connected edges from the canvas.',
      parameters: [
        param('node_id', 'string', 'ID of the node to delete', true)
      ],
      handler: 'custom',
      handlerFn: async (args) => {
        const nodeId = String(args.node_id)
        const node = ctx.getNodes().find(n => n.id === nodeId)
        if (!node) return `Error: Node '${nodeId}' not found`
        ctx.deleteNode(nodeId)
        return `Deleted node '${nodeId}' (${node.data.label}) and its connections`
      }
    },

    {
      name: 'connect_nodes',
      description: 'Create a connection (edge) between two nodes. For condition nodes, specify sourceHandle as "true" or "false".',
      parameters: [
        param('source', 'string', 'Source node ID', true),
        param('target', 'string', 'Target node ID', true),
        param('source_handle', 'string', 'Source handle ID for condition nodes: "true" or "false"', false)
      ],
      handler: 'custom',
      handlerFn: async (args) => {
        const source = String(args.source)
        const target = String(args.target)
        if (!ctx.getNodes().find(n => n.id === source)) return `Error: Source node '${source}' not found`
        if (!ctx.getNodes().find(n => n.id === target)) return `Error: Target node '${target}' not found`
        const existing = ctx.getEdges().find(e => e.source === source && e.target === target && e.sourceHandle === (args.source_handle || null))
        if (existing) return `Edge already exists from '${source}' to '${target}'`
        ctx.addEdge(source, target, args.source_handle ? String(args.source_handle) : undefined)
        return `Connected '${source}' → '${target}'${args.source_handle ? ` (handle: ${args.source_handle})` : ''}`
      }
    },

    {
      name: 'disconnect_nodes',
      description: 'Remove a specific edge/connection between two nodes.',
      parameters: [
        param('source', 'string', 'Source node ID', true),
        param('target', 'string', 'Target node ID', true)
      ],
      handler: 'custom',
      handlerFn: async (args) => {
        const edge = ctx.getEdges().find(e => e.source === String(args.source) && e.target === String(args.target))
        if (!edge) return `Error: No edge from '${args.source}' to '${args.target}'`
        ctx.deleteEdge(edge.id)
        return `Disconnected '${args.source}' → '${args.target}'`
      }
    },

    {
      name: 'validate_workflow',
      description: 'Check the workflow for issues: disconnected nodes, missing configs, no start node, etc.',
      parameters: [],
      handler: 'custom',
      handlerFn: async () => {
        const nodes = ctx.getNodes()
        const edges = ctx.getEdges()
        const issues: string[] = []

        const hasStart = nodes.some(n => ['manual-trigger', 'webhook-trigger', 'schedule-trigger'].includes(n.data.type))
        if (!hasStart) issues.push('No trigger/start node found')

        const nonComment = nodes.filter(n => n.data.type !== 'comment')
        for (const n of nonComment) {
          const hasIncoming = edges.some(e => e.target === n.id)
          const hasOutgoing = edges.some(e => e.source === n.id)
          const isTrigger = ['manual-trigger', 'webhook-trigger', 'schedule-trigger'].includes(n.data.type)
          if (!isTrigger && !hasIncoming) issues.push(`Node '${n.data.label}' (${n.id}) has no incoming connections`)
          if (n.data.type !== 'comment' && !hasOutgoing && n.data.type !== 'comment') {
            const isTerminal = ['comment'].includes(n.data.type)
            if (!isTerminal && !hasOutgoing) issues.push(`Node '${n.data.label}' (${n.id}) has no outgoing connections`)
          }
          if (n.data.type === 'llm' && !n.data.config?.model) issues.push(`LLM node '${n.data.label}' has no model configured`)
        }

        if (issues.length === 0) return 'Workflow is valid. No issues found.'
        return `Found ${issues.length} issue(s):\n${issues.map((i, idx) => `${idx + 1}. ${i}`).join('\n')}`
      }
    },

    {
      name: 'auto_layout',
      description: 'Automatically rearrange all nodes on the canvas for a clean layout.',
      parameters: [],
      handler: 'custom',
      handlerFn: async () => {
        ctx.autoLayout()
        return 'Auto-layout applied to all nodes'
      }
    },

    {
      name: 'describe_plan',
      description: 'Describe a plan to the user before executing. Use this to explain what you intend to do and ask for confirmation.',
      parameters: [
        param('plan', 'string', 'Description of what you plan to do', true)
      ],
      handler: 'custom',
      handlerFn: async (args) => {
        return `Plan: ${args.plan}`
      }
    }
  ]
}
