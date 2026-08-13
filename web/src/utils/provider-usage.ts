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
