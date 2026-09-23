/**
 * Zod schemas for the settings editor.
 *
 * Mirrors the backend rules (``app/services/agent_fs.py`` +
 * ``app/agent/loader.py``) so the UI surfaces errors immediately, without a
 * round-trip.  The backend still validates independently on save — this is a
 * UX layer, not a trust boundary.
 *
 * Every exported schema has a matching ``validateXxx(raw)`` helper that
 * returns ``string | null`` (the first error message or ``null`` when
 * valid).  Helpers are preferred in rendering code because they avoid
 * dealing with ``SafeParseReturn`` objects in JSX.
 */
import { z } from 'zod'
import { splitFrontmatter, unquoteYamlScalar } from './frontmatter'

z.config({ jitless: true })

// ── Primitive field schemas ──────────────────────────────────────────────────

/**
 * Agent / skill filename stem.  Matches
 * ``app/services/agent_fs.py::_NAME_RE`` byte-for-byte.
 */
export const agentNameSchema = z
  .string()
  .min(1, 'Required')
  .max(64, 'Max 64 characters')
  .regex(
    /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/,
    "Use letters, digits, '.', '_', '-' only (must start with a letter or digit)"
  )

/**
 * ``provider:model`` identifier.  Both halves must be non-empty; we do NOT
 * enforce a known-provider list here because the backend accepts custom
 * models (e.g. ``nvidia:custom-model``) and we don't want to block them.
 */
export const modelSchema = z
  .string()
  .regex(
    /^[a-zA-Z0-9_-]+:[^\s]+$/,
    "Expected 'provider:model' (e.g. 'openai:gpt-5.4')"
  )

/** Agent role — exactly one file in the team must be ``lead``. */
export const roleSchema = z.enum(['lead', 'member'])

/**
 * Thinking level — empty string means "unset".
 *
 * Levels are model metadata, not a closed frontend enum. Providers already
 * advertise values such as ``minimal``, ``xhigh``, ``max`` and ``ultra``;
 * keeping a hard-coded subset here made Agent Settings reject values that
 * the composer and backend accept.
 */
export const thinkingLevelSchema = z
  .string()
  .max(64, 'Max 64 characters')

/** Short one-line description; empty string is allowed. */
export const descriptionSchema = z
  .string()
  .max(1024, 'Max 1024 characters')

// ── Skill field schemas ─────────────────────────────────────────────────────
//
// Mirror the strict authoring rules in ``app/agent/skills/spec.py`` (the
// Agent Skills specification plus Anthropic's constraints). See
// ``documents/architecture/agent-skills.md``.

export const SKILL_NAME_MAX_CHARS = 64
export const SKILL_DESCRIPTION_MAX_CHARS = 1024
/** Words a Skill name must not contain. */
export const SKILL_RESERVED_NAME_WORDS = ['anthropic', 'claude'] as const
/** Flat Skill name: lowercase letters, digits and single hyphens. */
export const SKILL_NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
/** Same XML tag pattern the backend rejects in ``name`` / ``description``. */
const XML_TAG_RE = /<\s*\/?\s*[A-Za-z][\w.:-]*(?:\s[^<>]*)?\/?\s*>/

/** Skill name — also the name of the Skill's directory. */
export const skillNameSchema = z
  .string()
  .min(1, 'Required')
  .max(SKILL_NAME_MAX_CHARS, `Max ${SKILL_NAME_MAX_CHARS} characters`)
  .regex(
    SKILL_NAME_RE,
    "Use lowercase letters, digits, and single hyphens (for example 'code-review')",
  )
  .refine(
    (value) => !SKILL_RESERVED_NAME_WORDS.some((word) => value.includes(word)),
    { message: "Must not contain 'anthropic' or 'claude'" },
  )

/** What the Skill does and when to use it — the model sees this in its catalog. */
export const skillDescriptionSchema = z
  .string()
  .trim()
  .min(1, 'Required — the agent uses it to decide when to read the skill')
  .max(SKILL_DESCRIPTION_MAX_CHARS, `Max ${SKILL_DESCRIPTION_MAX_CHARS} characters`)
  .refine((value) => !XML_TAG_RE.test(value), { message: 'Must not contain XML tags' })

export const skillFrontmatterSchema = z.object({
  name: skillNameSchema,
  description: skillDescriptionSchema,
})

export type SkillFrontmatterParsed = z.infer<typeof skillFrontmatterSchema>

export function validateSkillName(raw: string): string | null {
  return firstError(skillNameSchema, raw)
}

export function validateSkillForm(
  fm: unknown
): Record<string, string> | null {
  const result = skillFrontmatterSchema.safeParse(fm)
  if (result.success) return null
  const errors: Record<string, string> = {}
  for (const issue of result.error.issues) {
    const path = issue.path.join('.') || '_root'
    if (!(path in errors)) errors[path] = issue.message
  }
  return errors
}

// ── Composite schema (whole frontmatter) ─────────────────────────────────────

/**
 * Shape of the agent form — keep in sync with
 * ``frontmatter.ts::AgentFrontmatter``.
 *
 * ``model`` is required (every agent needs one).  ``fallback_model`` is
 * optional and only validated when non-empty.  Everything else is
 * optional/nullable to accommodate the "unset" UI state.
 */
export const agentFrontmatterSchema = z.object({
  name: agentNameSchema,
  role: roleSchema,
  description: descriptionSchema.nullable().optional(),
  model: modelSchema,
  fallback_model: modelSchema.nullable().optional(),
  thinking_level: thinkingLevelSchema.nullable().optional(),
  tools: z.array(z.string()).optional(),
  skills: z.array(z.string()).optional(),
  mcp: z.array(z.string()).optional(),
})

export type AgentFrontmatterParsed = z.infer<typeof agentFrontmatterSchema>

/**
 * Full-form validation — returns a map of ``{ field → error message }``
 * for the fields that fail, or ``null`` if every field is valid.
 * Called by editor pages right before Save.
 */
export function validateAgentForm(
  fm: unknown
): Record<string, string> | null {
  const result = agentFrontmatterSchema.safeParse(fm)
  if (result.success) return null
  const errors: Record<string, string> = {}
  for (const issue of result.error.issues) {
    const path = issue.path.join('.') || '_root'
    // Keep the first error per field.
    if (!(path in errors)) errors[path] = issue.message
  }
  return errors
}

// ── Single-field helpers (UX-friendly) ───────────────────────────────────────

/**
 * Return the first validation error for ``raw`` or ``null`` when valid.
 * Generic over any zod schema — used by the ``Field`` wrapper to show
 * inline messages underneath the control.
 */
export function firstError<T>(schema: z.ZodType<T>, raw: unknown): string | null {
  const r = schema.safeParse(raw)
  return r.success ? null : (r.error.issues[0]?.message ?? 'Invalid')
}

export function validateAgentName(raw: string): string | null {
  return firstError(agentNameSchema, raw)
}

export function validateModel(
  raw: string,
  opts: { required?: boolean; validValues?: readonly string[] } = {}
): string | null {
  if (!raw) return opts.required ? 'Required' : null
  const shape = firstError(modelSchema, raw)
  if (shape) return shape
  // If the caller supplied the list of known registry models, reject any
  // value that isn't one of them. (The list is omitted while the registry
  // is loading, in which case we only enforce the shape.)
  if (opts.validValues && opts.validValues.length > 0 && !opts.validValues.includes(raw)) {
    return 'Not in the provider model list'
  }
  return null
}

export function validateDescription(raw: string): string | null {
  if (!raw) return null // empty is fine
  return firstError(descriptionSchema, raw)
}

// ── Whole-draft validators ──────────────────────────────────────────────────

/**
 * Validate a raw ``.md`` draft (frontmatter + body) against the agent schema.
 * Returns ``null`` if valid, or a ``{ field → message }`` map for the first
 * error encountered per field.  A missing / malformed frontmatter returns
 * ``{ _root: '<parser message>' }``.
 */
export function validateAgentDraft(raw: string): Record<string, string> | null {
  const { fm: fmText } = splitFrontmatter(raw)
  if (!fmText.trim()) {
    return { _root: 'Missing YAML frontmatter (needs --- … --- header).' }
  }
  let fm: Record<string, unknown>
  try {
    fm = parseLooseYaml(fmText)
  } catch (err) {
    return { _root: (err as Error).message }
  }
  // The schema is strict about ``name`` and ``model`` being present.
  return validateAgentForm(fm)
}

/**
 * Validate a raw ``SKILL.md`` draft. When ``expectedName`` is given (editing
 * an existing Skill), the frontmatter ``name`` must equal it because it must
 * match the Skill's directory.
 */
export function validateSkillDraft(
  raw: string,
  opts: { expectedName?: string } = {},
): Record<string, string> | null {
  const { fm: fmText, body } = splitFrontmatter(raw)
  if (!fmText.trim()) {
    return { _root: 'Missing YAML frontmatter (needs --- … --- header).' }
  }
  let fm: Record<string, unknown>
  try {
    fm = parseLooseYaml(fmText)
  } catch (err) {
    return { _root: (err as Error).message }
  }
  const errors = validateSkillForm(fm)
  if (errors) return errors
  if (opts.expectedName !== undefined && fm.name !== opts.expectedName) {
    return { name: `Name must stay '${opts.expectedName}' (it matches the skill folder)` }
  }
  if (!body.trim()) {
    return { body: 'Add instructions below the frontmatter' }
  }
  return null
}

/** Frontmatter ``name`` of a ``SKILL.md`` draft, or ``null`` when absent. */
export function skillDraftName(raw: string): string | null {
  const { fm: fmText } = splitFrontmatter(raw)
  if (!fmText.trim()) return null
  const name = parseLooseYaml(fmText).name
  return typeof name === 'string' && name ? name : null
}

/**
 * Minimal YAML parser — handles scalars, string lists, and the ``name:``
 * / ``description:`` header we care about.  Mirrors the parser in
 * ``AgentForm.parseSimpleYaml`` but without the form-specific type coercion.
 */
function parseLooseYaml(text: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const lines = text.split(/\r?\n/)
  let currentList: string[] | null = null
  // Multi-line scalar being collected: a block scalar (``key: >`` /
  // ``key: |``) or a plain scalar continued on indented lines.
  let pending: { key: string; joiner: string; lines: string[]; plain: boolean } | null = null

  const flushPending = () => {
    if (!pending) return
    const joined = pending.lines.join(pending.joiner).trim()
    out[pending.key] = pending.plain ? coerceScalar(unquoteYamlScalar(joined)) : joined
    pending = null
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (pending && /^\s/.test(line) && !/^\s+-\s/.test(line)) {
      pending.lines.push(line.trim())
      continue
    }
    if (pending && !line.trim() && !pending.plain) {
      pending.lines.push('')
      continue
    }
    flushPending()
    if (!line.trim() || line.trim().startsWith('#')) continue

    const listMatch = /^\s+-\s+(.*)$/.exec(line)
    if (currentList && listMatch) {
      currentList.push(unquoteYamlScalar(listMatch[1]))
      continue
    }

    const kvMatch = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
    if (!kvMatch) continue
    const [, key, rawValue] = kvMatch
    currentList = null

    if (rawValue === '') {
      currentList = []
      out[key] = currentList
      continue
    }
    const blockMatch = /^([>|])[+-]?\d*$/.exec(rawValue.trim())
    pending = blockMatch
      ? { key, joiner: blockMatch[1] === '>' ? ' ' : '\n', lines: [], plain: false }
      : { key, joiner: ' ', lines: [rawValue], plain: true }
  }
  flushPending()
  return out
}

function coerceScalar(v: string): unknown {
  if (v === 'true') return true
  if (v === 'false') return false
  if (v === 'null' || v === '~' || v === '') return null
  const n = Number(v)
  if (!Number.isNaN(n) && v.trim() !== '') return n
  return v
}
