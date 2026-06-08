import { memo, useMemo } from 'react'
import { getBezierPath, EdgeLabelRenderer, type EdgeProps } from 'reactflow'

interface EdgeData {
  status?: 'idle' | 'active' | 'completed' | 'error'
  isBackEdge?: boolean
  condition?: string
  iteration?: number
  maxIterations?: number
}

function getBackEdgePath({
  sourceX, sourceY, targetX, targetY
}: {
  sourceX: number; sourceY: number; targetX: number; targetY: number
}): [string, number, number] {
  const isBelow = sourceY < targetY
  const offsetX = isBelow ? 80 : 0
  const arcSide = sourceX < targetX ? -1 : 1

  const midY = (sourceY + targetY) / 2
  const controlX = (sourceX + targetX) / 2 + arcSide * offsetX
  const controlY1 = sourceY + (midY - sourceY) * 0.6
  const controlY2 = targetY - (targetY - midY) * 0.6

  const path = `M ${sourceX} ${sourceY} C ${controlX} ${controlY1}, ${controlX} ${controlY2}, ${targetX} ${targetY}`
  const labelX = controlX
  const labelY = midY

  return [path, labelX, labelY]
}

function CustomEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  style, label, markerEnd, data, source: _source, target: _target
}: EdgeProps<EdgeData>) {
  const isBackEdge = data?.isBackEdge || false
  const status = data?.status || 'idle'
  const condition = data?.condition
  const iteration = data?.iteration
  const maxIterations = data?.maxIterations

  const isReverseFlow = isBackEdge && sourceY >= targetY

  const [edgePath, labelX, labelY] = useMemo(() => {
    if (isBackEdge) {
      return getBackEdgePath({
        sourceX, sourceY, targetX, targetY
      })
    }
    return getBezierPath({
      sourceX, sourceY, sourcePosition,
      targetX, targetY, targetPosition
    })
  }, [isBackEdge, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition])

  const { stroke, strokeWidth, className, glowFilter } = useMemo(() => {
    if (isBackEdge && status === 'idle') {
      return {
        stroke: '#fbbf24',
        strokeWidth: 1.5,
        className: '',
        glowFilter: undefined
      }
    }

    switch (status) {
      case 'active':
        return {
          stroke: isBackEdge ? '#fbbf24' : '#60a5fa',
          strokeWidth: 2,
          className: 'edge-animated-running',
          glowFilter: isBackEdge ? 'url(#edge-glow-yellow)' : 'url(#edge-glow-blue)'
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
  }, [status, isBackEdge])

  const isActive = status === 'active'
  const hasStatus = status !== 'idle'

  const displayLabel = useMemo(() => {
    const parts: string[] = []
    if (label) parts.push(String(label))
    if (condition && !label) parts.push(condition.length > 20 ? condition.substring(0, 20) + '...' : condition)
    if (isBackEdge && iteration !== undefined) {
      const max = maxIterations || 100
      parts.push(`\u21BB ${iteration}/${max}`)
    }
    return parts.length > 0 ? parts.join(' ') : null
  }, [label, condition, isBackEdge, iteration, maxIterations])

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
        <filter id="edge-glow-yellow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur" />
          <feFlood floodColor="#fbbf24" floodOpacity="0.3" result="color" />
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
        strokeDasharray={isBackEdge && status === 'idle' ? '6 4' : undefined}
        style={{
          ...style,
          transition: 'stroke 0.3s ease, stroke-width 0.3s ease'
        }}
        markerEnd={markerEnd}
      />

      {isBackEdge && (
        <path
          d={edgePath}
          fill="none"
          stroke={stroke}
          strokeWidth={1}
          strokeOpacity={0.15}
          strokeDasharray="3 3"
          strokeLinecap="round"
        />
      )}

      {isActive && (
        <>
          <circle r="3.5" fill={isBackEdge ? '#fbbf24' : '#60a5fa'} opacity="0.9">
            <animateMotion
              dur={isBackEdge ? '2s' : '1.5s'}
              repeatCount="indefinite"
              path={edgePath}
              keyTimes="0;1"
              keyPoints={isReverseFlow ? '1;0' : '0;1'}
              calcMode="linear"
            />
          </circle>
          <circle r="3.5" fill={isBackEdge ? '#fbbf24' : '#60a5fa'} opacity="0.9">
            <animateMotion
              dur={isBackEdge ? '2s' : '1.5s'}
              repeatCount="indefinite"
              path={edgePath}
              begin={isBackEdge ? '1s' : '0.75s'}
              keyTimes="0;1"
              keyPoints={isReverseFlow ? '1;0' : '0;1'}
              calcMode="linear"
            />
          </circle>
        </>
      )}

      {status === 'completed' && (
        <circle r="3" fill="#34d399" opacity="0.6">
          <animateMotion dur="2s" repeatCount="indefinite" path={edgePath} />
        </circle>
      )}

      {displayLabel && (
        <EdgeLabelRenderer>
          <div style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            background: isBackEdge ? '#fbbf2415' : 'var(--bg-card)',
            padding: '3px 8px', borderRadius: 6,
            fontSize: 10,
            color: hasStatus ? stroke : isBackEdge ? '#fbbf24' : 'var(--text-secondary)',
            border: `1px solid ${hasStatus ? stroke + '40' : isBackEdge ? '#fbbf2440' : 'var(--border-primary)'}`,
            pointerEvents: 'all', fontWeight: 500,
            transition: 'all 0.3s ease',
            whiteSpace: 'nowrap'
          }}>
            {displayLabel}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export default memo(CustomEdge)
