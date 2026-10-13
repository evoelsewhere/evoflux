/**
 * TS mirror of the `ui_block` Pydantic models (spec §5.1) plus the
 * interactivity payload (§5.4). One block call carries `UiBlockNode[]`.
 *
 * NOTE (§8.3 stub rule): `UiChartBlock.spec` is deliberately `unknown` here
 * and `UiChart.tsx` renders a dependency-free placeholder. At merge, only the
 * `UiChart.tsx` body is re-pointed to the shared `parseChartSpec` +
 * Recharts `ChartBlock` renderer — this file stays untouched.
 */

export interface UiStatCard {
  label: string
  value: string | number
  delta?: string | null
  delta_tone?: 'up' | 'down' | 'neutral'
  hint?: string | null
}

export interface UiStatCardsBlock {
  type: 'stat_cards'
  cards: UiStatCard[]
}

export interface UiChartBlock {
  type: 'chart'
  /** ChartSpec — local structural type until merge re-points UiChart.tsx. */
  spec: unknown
}

export interface UiStep {
  title: string
  status?: 'done' | 'active' | 'pending' | 'error'
  detail?: string | null
}

export interface UiStepsBlock {
  type: 'steps'
  steps: UiStep[]
}

export interface UiTableBlock {
  type: 'table'
  /** key → header label mappings (server: list[dict[str, str]]). */
  columns: Record<string, string>[]
  rows: Record<string, unknown>[]
}

export interface UiKeyValueBlock {
  type: 'key_value'
  /** Each pair is a key → value mapping (server: list[dict[str, str]]). */
  pairs: Record<string, string>[]
}

export interface UiCalloutBlock {
  type: 'callout'
  tone?: 'info' | 'success' | 'warning' | 'error'
  title?: string | null
  body: string
}

export interface UiButton {
  label: string
  prompt: string
  style?: 'primary' | 'secondary'
}

export interface UiButtonsBlock {
  type: 'buttons'
  buttons: UiButton[]
}

export interface UiFormField {
  name: string
  label: string
  kind?: 'text' | 'textarea' | 'select' | 'checkbox'
  options?: string[]
  placeholder?: string | null
  default?: string | null
}

export interface UiFormBlock {
  type: 'form'
  title?: string | null
  fields: UiFormField[]
  submit_label?: string
}

export interface UiProgressBlock {
  type: 'progress'
  label: string
  value: number
  max: number
  unit?: string | null
}

export type UiBlockNode =
  | UiStatCardsBlock
  | UiChartBlock
  | UiStepsBlock
  | UiTableBlock
  | UiKeyValueBlock
  | UiCalloutBlock
  | UiButtonsBlock
  | UiFormBlock
  | UiProgressBlock

/** Round-trip payload (§5.4): buttons/forms send prompts; toggle is local. */
export type UiInteraction =
  | { kind: 'send_prompt'; prompt: string }
  | { kind: 'toggle'; id: string }

export type UiInteractionState = 'idle' | 'pending' | 'submitted' | 'failed'
