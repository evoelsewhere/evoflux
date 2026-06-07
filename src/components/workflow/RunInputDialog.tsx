import { useState, useEffect } from 'react'
import { Input, Modal } from 'antd'
import type { NodeData } from '../../types/workflow'
import type { Node } from 'reactflow'

const { TextArea } = Input

interface RunInputDialogProps {
  open: boolean
  nodes: Node<NodeData>[]
  onRun: (inputs: Record<string, unknown>) => void
  onCancel: () => void
}

interface VariableDef {
  name: string
  type?: string
  description?: string
  default?: unknown
}

export default function RunInputDialog({ open, nodes, onRun, onCancel }: RunInputDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({})

  const triggerNodes = nodes.filter(n => n.data.type === 'manual-trigger')
  const variables: VariableDef[] = triggerNodes.flatMap(n => {
    const cfg = n.data.config || {}
    const vars = cfg.variables
    return Array.isArray(vars) ? vars : []
  })

  useEffect(() => {
    if (open) {
      const init: Record<string, string> = {}
      for (const v of variables) {
        init[v.name] = v.default !== undefined ? String(v.default) : ''
      }
      setValues(init)
    }
  }, [open, variables.length])

  const handleOk = () => {
    const inputs: Record<string, unknown> = {}
    for (const [key, val] of Object.entries(values)) {
      const def = variables.find(v => v.name === key)
      if (def?.type === 'number' && val !== '') {
        inputs[key] = Number(val)
      } else if (def?.type === 'boolean') {
        inputs[key] = val === 'true'
      } else if (def?.type === 'json' && val) {
        try { inputs[key] = JSON.parse(val) } catch { inputs[key] = val }
      } else {
        inputs[key] = val
      }
    }
    onRun(inputs)
  }

  return (
    <Modal
      title="Run Workflow"
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      okText="Run"
      cancelText="Cancel"
      width={480}
      destroyOnClose
    >
      {variables.length === 0 ? (
        <div style={{ padding: '12px 0', fontSize: 13, color: 'var(--text-tertiary)' }}>
          No input variables defined. Add variables in the Start node config.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, paddingTop: 8 }}>
          {variables.map((v) => (
            <div key={v.name}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{v.name}</span>
                {v.type && <span style={{ fontSize: 9, color: 'var(--text-tertiary)', background: 'var(--bg-hover)', padding: '1px 5px', borderRadius: 3 }}>{v.type}</span>}
              </div>
              {v.description && <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 4 }}>{v.description}</div>}
              {v.type === 'json' ? (
                <TextArea rows={3} value={values[v.name] || ''} onChange={(e) => setValues(prev => ({ ...prev, [v.name]: e.target.value }))}
                  placeholder={v.default !== undefined ? String(v.default) : '{}'} style={{ fontSize: 12, fontFamily: 'monospace' }} />
              ) : (
                <Input size="small" value={values[v.name] || ''} onChange={(e) => setValues(prev => ({ ...prev, [v.name]: e.target.value }))}
                  placeholder={v.default !== undefined ? String(v.default) : v.description || `Enter ${v.name}`}
                  style={{ fontSize: 12 }} />
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}
