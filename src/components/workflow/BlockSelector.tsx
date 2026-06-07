import { useState } from 'react'
import { Input } from 'antd'
import { NODE_CATEGORIES, searchNodes, type NodeDefinition } from './registry'
import {
  NodeStartIcon, NodeGlobeIcon, NodeClockIcon, NodeLLMIcon,
  NodeExtractIcon, NodeTagIcon, NodeDatabaseIcon, NodeConditionIcon,
  NodeLoopIcon, NodeMergeIcon, NodeEditIcon, NodeTemplateIcon,
  NodeCodeIcon, NodeToolIcon, NodeFolderIcon,
  NodeAgentIcon, NodeTeamIcon, NodeSubWorkflowIcon
} from '../common/NodeIcons'

const ICON_MAP: Record<string, (sz: number, c: string) => React.ReactNode> = {
  'play-circle': (s, c) => <NodeStartIcon size={s} color={c} />,
  'global': (s, c) => <NodeGlobeIcon size={s} color={c} />,
  'clock-circle': (s, c) => <NodeClockIcon size={s} color={c} />,
  'robot': (s, c) => <NodeLLMIcon size={s} color={c} />,
  'scan': (s, c) => <NodeExtractIcon size={s} color={c} />,
  'tags': (s, c) => <NodeTagIcon size={s} color={c} />,
  'database': (s, c) => <NodeDatabaseIcon size={s} color={c} />,
  'branches': (s, c) => <NodeConditionIcon size={s} color={c} />,
  'reload': (s, c) => <NodeLoopIcon size={s} color={c} />,
  'sync': (s, c) => <NodeLoopIcon size={s} color={c} />,
  'merge-cells': (s, c) => <NodeMergeIcon size={s} color={c} />,
  'edit': (s, c) => <NodeEditIcon size={s} color={c} />,
  'file-text': (s, c) => <NodeTemplateIcon size={s} color={c} />,
  'code-sandbox': (s, c) => <NodeCodeIcon size={s} color={c} />,
  'code': (s, c) => <NodeCodeIcon size={s} color={c} />,
  'folder-open': (s, c) => <NodeFolderIcon size={s} color={c} />,
  'more': (s, c) => <NodeToolIcon size={s} color={c} />,
  'setting': (s, c) => <NodeToolIcon size={s} color={c} />,
  'apartment': (s, c) => <NodeSubWorkflowIcon size={s} color={c} />,
  'team': (s, c) => <NodeTeamIcon size={s} color={c} />,
  'unknown': (s, c) => <NodeToolIcon size={s} color={c} />
}

const CAT_COLORS: Record<string, string> = {
  trigger: '#34d399',
  ai: '#60a5fa',
  logic: '#fbbf24',
  tools: '#2dd4bf',
  agent: '#c084fc',
  other: '#a1a1aa'
}

interface BlockSelectorProps {
  onAddNode: (type: string, definition: NodeDefinition) => void
}

export default function BlockSelector({ onAddNode }: BlockSelectorProps) {
  const [search, setSearch] = useState('')

  const categories = search
    ? [{ name: 'Search Results', icon: 'more', nodes: searchNodes(search) }]
    : NODE_CATEGORIES

  const onDragStart = (e: React.DragEvent, nodeType: string, def: NodeDefinition) => {
    e.dataTransfer.setData('application/reactflow-type', nodeType)
    e.dataTransfer.setData('application/reactflow-def', JSON.stringify(def))
    e.dataTransfer.effectAllowed = 'move'
  }

  return (
    <div style={{
      width: 'var(--sidebar-width, 200px)',
      borderRight: '1px solid var(--border-primary)',
      background: 'var(--bg-secondary)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border-primary)' }}>
        <Input
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          size="small"
          allowClear
          style={{ fontSize: 12 }}
        />
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {categories.map((cat) => (
          <div key={cat.name} style={{ marginBottom: 2 }}>
            <div style={{
              padding: '5px 10px',
              fontSize: 10, fontWeight: 600,
              color: 'var(--text-tertiary)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em'
            }}>
              {cat.name}
            </div>

            {cat.nodes.map((node) => {
              const color = CAT_COLORS[node.category] || '#888'
              const iconFn = ICON_MAP[node.icon] || ICON_MAP['unknown']
              return (
                <button
                  key={node.type}
                  draggable
                  onDragStart={(e) => onDragStart(e, node.type, node)}
                  onClick={() => onAddNode(node.type, node)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 7,
                    width: '100%', padding: '5px 10px',
                    background: 'transparent', border: 'none',
                    cursor: 'grab', textAlign: 'left',
                    transition: 'background 0.1s', color: 'var(--text-secondary)'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-hover)'}
                  onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                >
                  <span style={{ display: 'flex', width: 16, justifyContent: 'center' }}>
                    {iconFn(12, color)}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-primary)' }}>{node.label}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-tertiary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {node.description}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
