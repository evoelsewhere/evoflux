import type { ProgressLedger } from '../../engine/agent/progress-ledger'

interface LedgerViewerProps {
  ledger: ProgressLedger | null
  round: number
  stallCount: number
  isRunning: boolean
}

export default function LedgerViewer({ ledger, round, stallCount, isRunning }: LedgerViewerProps) {
  if (!isRunning && !ledger) return null

  return (
    <div style={{
      padding: 12,
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-primary)',
      borderRadius: 8,
      marginBottom: 12
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
        Progress Ledger
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
          Round: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{round}</span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
          Stalls: <span style={{ color: stallCount > 0 ? 'var(--warning)' : 'var(--text-primary)', fontWeight: 500 }}>{stallCount}</span>
        </div>
      </div>

      {ledger && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <LedgerItem
            label="Request Satisfied"
            value={ledger.isRequestSatisfied.answer}
            reason={ledger.isRequestSatisfied.reason}
          />
          <LedgerItem
            label="Progress Being Made"
            value={ledger.isProgressBeingMade.answer}
            reason={ledger.isProgressBeingMade.reason}
          />
          <LedgerItem
            label="In Loop"
            value={ledger.isInLoop.answer}
            reason={ledger.isInLoop.reason}
            warn={ledger.isInLoop.answer}
          />
          {ledger.nextSpeaker.answer && (
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 4 }}>
              Next: <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{ledger.nextSpeaker.answer}</span>
              {ledger.nextSpeaker.reason && <span style={{ color: 'var(--text-tertiary)' }}> — {ledger.nextSpeaker.reason}</span>}
            </div>
          )}
          {ledger.instructionOrQuestion.answer && (
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
              Instruction: <span style={{ color: 'var(--text-secondary)' }}>{ledger.instructionOrQuestion.answer.substring(0, 200)}</span>
            </div>
          )}
        </div>
      )}

      {isRunning && !ledger && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-tertiary)' }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)', animation: 'pulse 1.5s infinite' }} />
          Evaluating...
        </div>
      )}
    </div>
  )
}

function LedgerItem({ label, value, reason, warn }: { label: string; value: boolean; reason: string; warn?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 11 }}>
      <div style={{
        width: 8, height: 8, borderRadius: '50%', marginTop: 2, flexShrink: 0,
        background: warn ? 'var(--warning)' : value ? 'var(--success)' : 'var(--text-tertiary)'
      }} />
      <div>
        <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>{label}</span>
        <span style={{ color: 'var(--text-tertiary)', marginLeft: 4 }}>
          {value ? 'Yes' : 'No'}{reason ? ` — ${reason}` : ''}
        </span>
      </div>
    </div>
  )
}
