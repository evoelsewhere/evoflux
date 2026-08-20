const PLAN_LABELS: Record<string, string> = {
  enterprise_cbp_usage_based: 'Enterprise usage-based',
}

export function formatProviderPlan(plan?: string | null): string | null {
  const normalized = plan?.trim()
  if (!normalized) return null
  if (PLAN_LABELS[normalized]) return PLAN_LABELS[normalized]

  const words = normalized.replaceAll('_', ' ').replaceAll('-', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function formatCreditNumber(value: string, locale?: string): string | null {
  if (!/^-?\d+(?:\.\d+)?$/.test(value.trim())) return null
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return null
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: 2,
  }).format(parsed)
}

function parseCreditNumber(value?: string | null): number | null {
  const normalized = value?.trim()
  if (!normalized || !/^-?\d+(?:\.\d+)?$/.test(normalized)) return null
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

export function formatCreditBalance(balance?: string | null, locale?: string): string | null {
  const normalized = balance?.trim()
  if (!normalized) return null

  const ratio = normalized.split('/')
  if (ratio.length === 2) {
    const remaining = formatCreditNumber(ratio[0], locale)
    const total = formatCreditNumber(ratio[1], locale)
    if (remaining && total) return `${remaining} / ${total}`
  }

  return formatCreditNumber(normalized, locale) ?? normalized
}

export type CreditUsageSummary = {
  used: number
  total: number
  usedPercent: number
  unit: string
  label: string
}

export function summarizeCreditUsage(
  credits?: {
    balance?: string | null
    used?: string | null
    total?: string | null
    unit?: string | null
  } | null,
  locale?: string,
): CreditUsageSummary | null {
  if (!credits) return null
  let used = parseCreditNumber(credits.used)
  let total = parseCreditNumber(credits.total)
  let remaining = parseCreditNumber(credits.balance)

  if ((total == null || remaining == null) && credits.balance?.includes('/')) {
    const [rawRemaining, rawTotal] = credits.balance.split('/', 2)
    remaining = parseCreditNumber(rawRemaining)
    total = parseCreditNumber(rawTotal)
  }
  if (used == null && total != null && remaining != null) {
    used = total - remaining
  }
  if (total == null || used == null || total <= 0 || used < 0 || used > total) {
    return null
  }

  const formattedUsed = formatCreditNumber(String(used), locale)
  const formattedTotal = formatCreditNumber(String(total), locale)
  if (!formattedUsed || !formattedTotal) return null
  const unit = credits.unit?.trim() || 'credits'
  return {
    used,
    total,
    usedPercent: Math.max(
      0,
      Math.min(100, Math.round((used / total) * 1_000_000) / 10_000),
    ),
    unit,
    label: `${formattedUsed} of ${formattedTotal} ${unit} used`,
  }
}

export function formatUsageWindowLabel(
  base: string,
  minutes?: number | null,
): string {
  if (typeof minutes !== 'number') return base
  const days = minutes / (60 * 24)
  const prefix = base === 'Codex' ? '' : `${base} · `
  if (days >= 27 && days <= 32) {
    if (base.toLowerCase() === 'premium requests') return 'Monthly premium requests'
    return base.toLowerCase() === 'monthly usage' ? base : `${prefix}Monthly usage`
  }
  if (days >= 6 && days <= 8) {
    return base.toLowerCase() === 'weekly usage' ? base : `${prefix}Weekly usage`
  }
  if (days >= 0.9 && days <= 1.1) {
    return base.toLowerCase() === 'daily usage' ? base : `${prefix}Daily usage`
  }
  if (minutes < 60) return `${base} · ${minutes}m window`
  if (minutes < 60 * 24) return `${base} · ${Math.round(minutes / 60)}h window`
  return `${base} · ${Math.round(days)}d window`
}

export function formatUsageReset(
  timestamp?: number | null,
  windowMinutes?: number | null,
  locale?: string,
  timeZone?: string,
): string | null {
  if (typeof timestamp !== 'number') return null
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return null
  const longWindow = typeof windowMinutes === 'number' && windowMinutes >= 60 * 24
  const value = longWindow
    ? date.toLocaleDateString(locale, { month: 'short', day: 'numeric', timeZone })
    : date.toLocaleTimeString(locale, {
        hour: '2-digit',
        minute: '2-digit',
        timeZone,
      })
  return `Resets ${value}`
}
