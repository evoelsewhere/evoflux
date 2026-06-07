import { memo } from 'react'
import { getBezierPath, EdgeLabelRenderer, type EdgeProps } from 'reactflow'

function CustomEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, label, markerEnd }: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })

  return (
    <>
      <path id={id} style={{ ...style, stroke: 'var(--border-secondary)', strokeWidth: 1.5 }} className="react-flow__edge-path" d={edgePath} markerEnd={markerEnd} />
      {label && (
        <EdgeLabelRenderer>
          <div style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, background: 'var(--bg-card)', padding: '3px 8px', borderRadius: 6, fontSize: 10, color: 'var(--text-secondary)', border: '1px solid var(--border-primary)', pointerEvents: 'all', fontWeight: 500 }}>
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export default memo(CustomEdge)
