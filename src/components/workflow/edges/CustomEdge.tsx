import { memo, useMemo } from 'react'
import { getBezierPath, EdgeLabelRenderer, type EdgeProps } from 'reactflow'

interface EdgeData {
  status?: 'idle' | 'active' | 'completed' | 'error'
}

function CustomEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  style, label, markerEnd, data, selected: _selected
}: EdgeProps<EdgeData>) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition,
    targetX, targetY, targetPosition
  })

  const status = data?.status || 'idle'

  const { stroke, strokeWidth, className, glowFilter } = useMemo(() => {
    switch (status) {
      case 'active':
        return {
          stroke: '#60a5fa',
          strokeWidth: 2,
          className: 'edge-animated-running',
          glowFilter: 'url(#edge-glow-blue)'
        }
      case 'completed':
        return {
          stroke: '#34d399',
          strokeWidth: 2,
          className: 'edge-animated-completed',
          glowFilter: 'url(#edge-glow-green)'
        }
      case 'error':
        return {
          stroke: '#f87171',
          strokeWidth: 2,
          className: 'edge-animated-error',
          glowFilter: 'url(#edge-glow-red)'
        }
      default:
        return {
          stroke: 'var(--border-secondary)',
          strokeWidth: 1.5,
          className: '',
          glowFilter: undefined
        }
    }
  }, [status])

  const isActive = status === 'active'
  const hasStatus = status !== 'idle'

  return (
    <>
      <defs>
        <filter id="edge-glow-blue" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
          <feFlood floodColor="#60a5fa" floodOpacity="0.4" result="color" />
          <feComposite in="color" in2="blur" operator="in" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="edge-glow-green" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
          <feFlood floodColor="#34d399" floodOpacity="0.3" result="color" />
          <feComposite in="color" in2="blur" operator="in" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="edge-glow-red" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
          <feFlood floodColor="#f87171" floodOpacity="0.3" result="color" />
          <feComposite in="color" in2="blur" operator="in" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {hasStatus && (
        <path
          d={edgePath}
          fill="none"
          stroke={stroke}
          strokeWidth={strokeWidth + 4}
          strokeOpacity={0.08}
          strokeLinecap="round"
        />
      )}

      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        className={className}
        filter={glowFilter}
        style={{
          ...style,
          transition: 'stroke 0.3s ease, stroke-width 0.3s ease'
        }}
        markerEnd={markerEnd}
      />

      {isActive && (
        <>
          <circle r="3.5" fill="#60a5fa" opacity="0.9">
            <animateMotion dur="1.5s" repeatCount="indefinite" path={edgePath} />
          </circle>
          <circle r="3.5" fill="#60a5fa" opacity="0.9">
            <animateMotion dur="1.5s" repeatCount="indefinite" path={edgePath} begin="0.75s" />
          </circle>
        </>
      )}

      {status === 'completed' && (
        <circle r="3" fill="#34d399" opacity="0.6">
          <animateMotion dur="2s" repeatCount="indefinite" path={edgePath} />
        </circle>
      )}

      {label && (
        <EdgeLabelRenderer>
          <div style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            background: 'var(--bg-card)',
            padding: '3px 8px', borderRadius: 6,
            fontSize: 10,
            color: hasStatus ? stroke : 'var(--text-secondary)',
            border: `1px solid ${hasStatus ? stroke + '40' : 'var(--border-primary)'}`,
            pointerEvents: 'all', fontWeight: 500,
            transition: 'all 0.3s ease'
          }}>
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export default memo(CustomEdge)
