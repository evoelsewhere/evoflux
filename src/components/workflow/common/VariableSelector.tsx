import { useState, useMemo } from 'react'
import { Input, Tree } from 'antd'
import { SearchOutlined, RightOutlined } from '@ant-design/icons'
import type { Node } from 'reactflow'

interface VariableSelectorProps {
  nodes: Node[]
  selectedNodeId?: string
  onSelect: (nodeId: string, key: string) => void
  currentValue?: string
}

interface TreeNode {
  title: string
  key: string
  children?: TreeNode[]
  isLeaf?: boolean
}

export default function VariableSelector({ nodes, selectedNodeId, onSelect, currentValue }: VariableSelectorProps) {
  const [search, setSearch] = useState('')

  const treeData = useMemo<TreeNode[]>(() => {
    return nodes
      .filter(n => n.id !== selectedNodeId)
      .map(node => ({
        title: node.data?.label || node.id,
        key: node.id,
        children: getNodeOutputs(node).map(key => ({
          title: key,
          key: `${node.id}.${key}`,
          isLeaf: true
        }))
      }))
      .filter(node => {
        if (!search) return true
        const q = search.toLowerCase()
        return node.title.toLowerCase().includes(q) ||
          node.children?.some(c => c.title.toLowerCase().includes(q))
      })
  }, [nodes, selectedNodeId, search])

  const handleSelect = (selectedKeys: React.Key[]) => {
    const key = String(selectedKeys[0] || '')
    if (!key) return
    const parts = key.split('.')
    if (parts.length === 2) {
      onSelect(parts[0], parts[1])
    }
  }

  return (
    <div>
      <Input
        prefix={<SearchOutlined style={{ color: 'var(--text-tertiary)', fontSize: 11 }} />}
        placeholder="Search variables..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        size="small"
        allowClear
        style={{ marginBottom: 8, fontSize: 12 }}
      />
      <Tree
        treeData={treeData}
        onSelect={handleSelect}
        showLine={{ showLeafIcon: false }}
        style={{ background: 'transparent', color: 'var(--text-primary)', fontSize: 12 }}
        selectedKeys={currentValue ? [currentValue] : []}
      />
    </div>
  )
}

function getNodeOutputs(node: Node): string[] {
  const type = node.data?.type
  switch (type) {
    case 'start':
    case 'manual-trigger':
      return Object.keys(node.data?.config?.variables || {}).length > 0
        ? (node.data.config.variables as Array<{ name: string }>).map(v => v.name)
        : ['output']
    case 'llm':
      return ['output', 'usage']
    case 'code':
      return ['output', 'error']
    case 'condition':
      return ['true_branch', 'false_branch', 'result']
    case 'http-request':
      return ['response', 'status', 'headers']
    case 'template':
      return ['output']
    case 'iteration':
      return ['results', 'current_item', 'index']
    case 'loop':
      return ['output', 'iterations']
    case 'variable-aggregator':
    case 'variable-assigner':
      return ['output']
    case 'react-agent':
      return ['output', 'iterations', 'thoughts']
    case 'agent-orchestrator':
      return ['output', 'results', 'rounds']
    case 'shell':
      return ['stdout', 'stderr', 'exit_code']
    case 'file-explorer':
      return ['files', 'file_count', 'root_path']
    case 'file-reader':
      return ['content', 'metadata']
    case 'context-loader':
      return ['context', 'tree', 'files_loaded']
    case 'parameter-extractor':
      return ['parameters', 'raw']
    case 'question-classifier':
      return ['category', 'confidence', 'raw']
    case 'knowledge-retrieval':
      return ['results', 'count']
    default:
      return ['output']
  }
}
