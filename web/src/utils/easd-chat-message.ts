const PHASE_LABELS: Record<string, string> = {
  'easd-specify': 'Specify',
  'easd-plan': 'Plan',
  'easd-implement': 'Implement',
  'easd-review': 'Review',
  'easd-verify': 'Verify',
}

const TECHNICAL_TOKEN = /(python -m pytest [\w./-]+|\b(?:easd_submit_specification|easd_submit_plan|easd_submit_review|team_delegate|CompletionContract)\b|(?:\.?[\w/-]+)\.(?:json|md|py)\b)/g

function redactRevisionHashes(value: string): string {
  return value
    .replace(/\bEASD run [0-9a-f]{8}-[0-9a-f-]{27,36}\b/gi, 'this EASD Run')
    .replace(/\b(?:this exact )?run ID [0-9a-f]{8}-[0-9a-f-]{27,36}\b/gi, 'this Run')
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, 'recorded Run')
    .replace(/\baccepted spec hash [0-9a-f]{16,64}(?=\b|\.\.\.)/gi, 'accepted Spec revision')
    .replace(/\baccepted plan hash [0-9a-f]{16,64}(?=\b|\.\.\.)/gi, 'accepted Plan revision')
    .replace(/\bspec hash [0-9a-f]{16,64}(?=\b|\.\.\.)/gi, 'Spec revision')
    .replace(/\bplan hash [0-9a-f]{16,64}(?=\b|\.\.\.)/gi, 'Plan revision')
    .replace(/\bhash [0-9a-f]{16,64}(?=\b|\.\.\.)/gi, 'recorded revision')
    .replace(/\b[0-9a-f]{16,64}(?=\b|\.\.\.)/gi, 'recorded revision')
}

function decorateTechnicalTokens(value: string): string {
  return value
    .split(/(`[^`\n]+`)/g)
    .map((segment) => (
      segment.startsWith('`') && segment.endsWith('`')
        ? segment
        : segment.replace(TECHNICAL_TOKEN, '`$1`')
    ))
    .join('')
}

export function parseEasdChatMessage(content: string): {
  directive: string
  phase: string
  body: string
} | null {
  const match = content.match(/^\$(easd-(?:specify|plan|implement|review|verify))\s*(?:\n+|$)/)
  if (!match) return null
  return {
    directive: `$${match[1]}`,
    phase: PHASE_LABELS[match[1]] ?? match[1],
    body: decorateTechnicalTokens(redactRevisionHashes(content.slice(match[0].length).trimStart())),
  }
}
