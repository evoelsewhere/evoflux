import { Skeleton } from 'antd'

export function WorkflowCardSkeleton() {
  return (
    <div style={{
      padding: 20, background: 'var(--bg-elevated)', border: '1px solid var(--border-primary)',
      borderRadius: 12, display: 'flex', flexDirection: 'column', gap: 12
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <Skeleton.Avatar size={36} shape="square" active />
        <Skeleton.Input size="small" style={{ width: 50, height: 20 }} active />
      </div>
      <Skeleton.Input size="small" style={{ width: '70%', height: 16 }} active />
      <Skeleton.Input size="small" style={{ width: '100%', height: 12 }} active />
      <Skeleton.Input size="small" style={{ width: '40%', height: 12 }} active />
    </div>
  )
}

export function WorkflowListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
      {Array.from({ length: count }).map((_, i) => (
        <WorkflowCardSkeleton key={i} />
      ))}
    </div>
  )
}

export function NodeExecutionSpinner({ status }: { status: string }) {
  if (status === 'idle') return null
  return (
    <div style={{
      position: 'absolute', top: -4, right: -4,
      width: 12, height: 12, borderRadius: '50%',
      background: status === 'running' ? 'var(--accent)' :
        status === 'completed' ? 'var(--success)' :
          status === 'error' ? 'var(--error)' : 'transparent',
      border: '2px solid var(--bg-card)',
      animation: status === 'running' ? 'pulse 1.5s infinite' : 'none',
      zIndex: 5
    }} />
  )
}

export function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div style={{
      width: '100%', height: 4, background: 'var(--border-primary)',
      borderRadius: 2, overflow: 'hidden'
    }}>
      <div style={{
        width: `${pct}%`, height: '100%', background: 'var(--accent)',
        borderRadius: 2, transition: 'width 0.3s ease'
      }} />
    </div>
  )
}
