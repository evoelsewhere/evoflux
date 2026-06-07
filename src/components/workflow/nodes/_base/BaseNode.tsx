import { memo } from 'react'
import { Handle, Position, type NodeProps } from 'reactflow'
import {
  NodeStartIcon, NodeEndIcon, NodeLLMIcon, NodeCodeIcon,
  NodeConditionIcon, NodeTemplateIcon, NodeLoopIcon,
  NodeMergeIcon, NodeDatabaseIcon, NodeTeamIcon,
  NodeFolderIcon, NodeClockIcon, NodeGlobeIcon, NodeToolIcon,
  NodeExtractIcon, NodeTagIcon, NodeEditIcon,
  NodeSubWorkflowIcon
} from '../../../common/NodeIcons'

const ICONS: Record<string, (sz: number, c: string) => React.ReactNode> = {
  'play-circle': (s, c) => <NodeStartIcon size={s} color={c} />,
  'stop-circle': (s, c) => <NodeEndIcon size={s} color={c} />,
  'robot': (s, c) => <NodeLLMIcon size={s} color={c} />,
  'code-sandbox': (s, c) => <NodeCodeIcon size={s} color={c} />,
  'code': (s, c) => <NodeCodeIcon size={s} color={c} />,
  'branches': (s, c) => <NodeConditionIcon size={s} color={c} />,
  'global': (s, c) => <NodeGlobeIcon size={s} color={c} />,
  'file-text': (s, c) => <NodeTemplateIcon size={s} color={c} />,
  'reload': (s, c) => <NodeLoopIcon size={s} color={c} />,
  'sync': (s, c) => <NodeLoopIcon size={s} color={c} />,
  'edit': (s, c) => <NodeEditIcon size={s} color={c} />,
  'merge-cells': (s, c) => <NodeMergeIcon size={s} color={c} />,
  'database': (s, c) => <NodeDatabaseIcon size={s} color={c} />,
  'scan': (s, c) => <NodeExtractIcon size={s} color={c} />,
  'tags': (s, c) => <NodeTagIcon size={s} color={c} />,
  'team': (s, c) => <NodeTeamIcon size={s} color={c} />,
  'folder-open': (s, c) => <NodeFolderIcon size={s} color={c} />,
  'clock-circle': (s, c) => <NodeClockIcon size={s} color={c} />,
  'apartment': (s, c) => <NodeSubWorkflowIcon size={s} color={c} />,
  'more': (s, c) => <NodeToolIcon size={s} color={c} />,
  'setting': (s, c) => <NodeToolIcon size={s} color={c} />,
  'unknown': (s, c) => <NodeToolIcon size={s} color={c} />
}

interface CatStyle { bg: string; bgSel: string; accent: string; bar: string; text: string }

const CAT: Record<string, CatStyle> = {
  trigger: { bg: '#0f1a14', bgSel: '#132a1d', accent: '#34d399', bar: '#065f46', text: '#6ee7b7' },
  ai:      { bg: '#0f172a', bgSel: '#172554', accent: '#60a5fa', bar: '#1e40af', text: '#93c5fd' },
  logic:   { bg: '#1c1917', bgSel: '#292524', accent: '#fbbf24', bar: '#92400e', text: '#fcd34d' },
  tools:   { bg: '#131c1c', bgSel: '#1a2e2e', accent: '#2dd4bf', bar: '#115e59', text: '#5eead4' },
  agent:   { bg: '#1e1028', bgSel: '#2e1040', accent: '#c084fc', bar: '#7e22ce', text: '#d8b4fe' },
  other:   { bg: '#18181b', bgSel: '#27272a', accent: '#a1a1aa', bar: '#3f3f46', text: '#d4d4d8' }
}

interface BaseNodeData {
  label: string
  type: string
  icon?: string
  category?: string
  config?: Record<string, unknown>
  status?: 'idle' | 'running' | 'completed' | 'error'
  error?: string
  text?: string
}

function getSubtitle(data: BaseNodeData): string | null {
  const cfg = data.config || {}
  switch (data.type) {
    case 'llm':
    case 'react-agent':
      return cfg.prompt ? String(cfg.prompt).substring(0, 40) : cfg.model ? String(cfg.model) : null
    case 'condition':
      return cfg.expression ? String(cfg.expression).substring(0, 40) : null
    case 'template':
      return cfg.template ? String(cfg.template).substring(0, 40) : null
    case 'code':
      return cfg.language ? String(cfg.language) : null
    case 'shell':
      return cfg.command ? String(cfg.command).substring(0, 40) : null
    case 'http-request':
      return cfg.url ? `${cfg.method || 'GET'} ${String(cfg.url).substring(0, 30)}` : null
    case 'loop':
      return cfg.condition ? `while: ${String(cfg.condition).substring(0, 30)}` : null
    case 'iteration':
      return cfg.array_input ? `each: ${String(cfg.array_input).substring(0, 30)}` : null
    case 'file-explorer':
      return cfg.root_path ? String(cfg.root_path).substring(0, 40) : null
    case 'file-reader':
      return cfg.path ? String(cfg.path).substring(0, 40) : null
    case 'file-write':
      return cfg.path ? `→ ${String(cfg.path).substring(0, 35)}` : null
    case 'context-loader':
      return cfg.root_path ? String(cfg.root_path).substring(0, 40) : null
    case 'parameter-extractor':
      return cfg.parameters ? `${(cfg.parameters as unknown[])?.length || 0} params` : null
    case 'question-classifier':
      return cfg.categories ? (cfg.categories as string[])?.join(', ').substring(0, 40) : null
    case 'knowledge-retrieval':
      return cfg.query ? String(cfg.query).substring(0, 40) : null
    case 'agent-orchestrator':
      return cfg.task ? String(cfg.task).substring(0, 40) : null
    case 'sub-workflow':
      return cfg.workflow_id ? String(cfg.workflow_id).substring(0, 40) : null
    case 'webhook-trigger':
      return cfg.path ? String(cfg.path) : null
    case 'schedule-trigger':
      return cfg.cron ? String(cfg.cron) : null
    case 'variable-aggregator':
      return cfg.output_key ? `→ ${cfg.output_key}` : null
    case 'variable-assigner':
      return cfg.variable_name ? `${cfg.variable_name} = ${String(cfg.value || '').substring(0, 20)}` : null
    case 'manual-trigger':
      return cfg.variables ? `${(cfg.variables as unknown[])?.length || 0} vars` : null
    case 'comment':
      return data.text ? String(data.text).substring(0, 50) : null
    default:
      return cfg.prompt ? String(cfg.prompt).substring(0, 40) : null
  }
}

function BaseNodeComponent({ data, selected }: NodeProps<BaseNodeData>) {
  const cat = CAT[data.category || 'tools'] || CAT.tools
  const iconFn = ICONS[data.icon || ''] || ICONS['unknown']
  const isCondition = data.type === 'condition'

  const statusColor = data.status === 'running' ? '#60a5fa'
    : data.status === 'completed' ? '#34d399'
    : data.status === 'error' ? '#f87171'
    : undefined

  const subtitle = getSubtitle(data)

  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        style={{
          width: 8, height: 8,
          background: statusColor || cat.accent,
          border: `2px solid ${cat.bar}`,
          top: -4, zIndex: 10
        }}
      />

      <div style={{
        background: selected ? cat.bgSel : cat.bg,
        border: `1px solid ${statusColor || (selected ? cat.accent + '66' : cat.bar)}`,
        borderRadius: 8,
        minWidth: 150,
        maxWidth: 200,
        boxShadow: selected ? `0 0 12px ${cat.accent}20` : 'none',
        transition: 'all 0.12s ease',
        overflow: 'hidden'
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 10px',
          background: selected ? cat.accent + '0d' : 'transparent',
          borderBottom: `1px solid ${cat.bar}44`
        }}>
          <span style={{ display: 'flex', opacity: 0.9 }}>{iconFn(12, cat.accent)}</span>
          <span style={{
            color: cat.text, fontWeight: 600, fontSize: 11, flex: 1,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            letterSpacing: '-0.01em'
          }}>
            {data.label}
          </span>
          {statusColor && (
            <div style={{
              width: 5, height: 5, borderRadius: '50%',
              background: statusColor,
              boxShadow: `0 0 6px ${statusColor}`,
              animation: data.status === 'running' ? 'pulse 1.5s infinite' : 'none'
            }} />
          )}
        </div>

        <div style={{ padding: '5px 10px', minHeight: 16 }}>
          {subtitle && (
            <div style={{ color: cat.text + '55', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {subtitle}
            </div>
          )}
          {data.status === 'error' && data.error && (
            <div style={{
              marginTop: 2, padding: '2px 5px',
              background: '#f8717120', borderRadius: 3,
              fontSize: 9, color: '#f87171',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'
            }}>
              {data.error.substring(0, 45)}
            </div>
          )}
        </div>

        {isCondition && (
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 10px 5px', borderTop: `1px solid ${cat.bar}44` }}>
            <span style={{ color: '#34d399', fontSize: 9, fontWeight: 600 }}>
              {data.config?.true_label as string || 'Yes'}
            </span>
            <span style={{ color: '#f87171', fontSize: 9, fontWeight: 600 }}>
              {data.config?.false_label as string || 'No'}
            </span>
          </div>
        )}
      </div>

      {isCondition ? (
        <>
          <Handle
            type="source"
            position={Position.Bottom}
            id="true"
            style={{
              width: 8, height: 8,
              background: statusColor || '#34d399',
              border: '2px solid #065f46',
              bottom: -4, left: '30%', zIndex: 10
            }}
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="false"
            style={{
              width: 8, height: 8,
              background: statusColor || '#f87171',
              border: '2px solid #991b1b',
              bottom: -4, left: '70%', zIndex: 10
            }}
          />
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Bottom}
          style={{
            width: 8, height: 8,
            background: statusColor || cat.accent,
            border: `2px solid ${cat.bar}`,
            bottom: -4, zIndex: 10
          }}
        />
      )}
    </>
  )
}

export default memo(BaseNodeComponent)
