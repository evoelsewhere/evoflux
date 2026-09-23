/**
 * Composer token grammar — the single source of truth for which ``/command``
 * and ``$skill-name`` substrings are *live* directives rather than plain
 * prose.
 *
 * Both the composer overlay (while typing) and the transcript renderer
 * (after send) use these helpers, so a token looks the same before and
 * after the message leaves the input.
 *
 * The rules mirror what actually consumes each token on the way out:
 *
 *   - ``$skill-name`` — ``app/agent/skills/invocation.py`` (``MENTION_RE``
 *     and ``skill_mentions``). A mention is ``$`` followed by a valid Skill
 *     name (lowercase letters, digits, single hyphens), not preceded by a
 *     word character or another ``$``, and followed by whitespace,
 *     punctuation or the end of the text. Mentions count anywhere in the
 *     message — several per message — except in quoted context lines
 *     (``> ...``) and fenced code blocks. Keep this module in step with that
 *     Python module.
 *   - ``/command`` — the front-end interceptors (``parseGoalCommand``,
 *     ``parseWorkflowCommand``, ``expandUserCommand``) all test the trimmed
 *     message's first token, so only a leading command is live.
 */

/** Command name: ``compact`` or one level of ``git:commit``. */
const COMMAND_NAME = '[a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?'
const COMMAND_RE = new RegExp(`^/(${COMMAND_NAME})(?=\\s|$)`)
/** ``$name`` body plus the backend's terminator lookahead (``MENTION_RE``). */
const MENTION_NAME_RE = /^([a-z0-9]+(?:-[a-z0-9]+)*)(?=$|[\s.,!?;:)\]}'"])/
/** A ``$`` glued to one of these is part of a word/variable, not a mention. */
const MENTION_HEAD_RE = /[A-Za-z0-9_$]/
/** Opening or closing line of a fenced code block. */
const FENCE_RE = /^\s*(```|~~~)/
/**
 * Heuristic used when no skill roster is available (the transcript renders
 * old messages without querying the skill list): the name must start with a
 * letter and be at least two characters, so ``$5`` and ``$100`` stay plain.
 */
const MENTION_HEURISTIC_RE = /^[a-z][a-z0-9-]+$/

export interface SkillDirectiveRange {
  start: number
  end: number
  name: string
}

export interface TokenRange {
  start: number
  end: number
  name: string
}

/**
 * Locate the first real content line — quote-context lines (``>`` prefixed)
 * and blank lines are skipped.
 *
 * Returns the line text plus its absolute offset in ``text``, or ``null``
 * when the message is nothing but quotes and blanks.
 */
export function firstContentLine(text: string): { line: string; offset: number } | null {
  let offset = 0
  for (const line of text.split('\n')) {
    if (line !== '' && line !== '>' && !line.startsWith('> ')) {
      return { line, offset }
    }
    offset += line.length + 1
  }
  return null
}

/**
 * Split a composed message into its leading quote block and the body.
 *
 * The composer prepends "Selected from chat" as ``> `` lines followed by a
 * blank line, so the user's actual text — and any command opening it — no
 * longer sits at index 0. Every command interceptor matches on the message's
 * first token, which is why they need the body, not the raw content.
 *
 * ``quote`` keeps its markers and trailing separator verbatim, so
 * ``quote + body`` reproduces the original message exactly.
 */
export function splitQuotedContext(text: string): { quote: string; body: string } {
  const content = firstContentLine(text)
  if (!content || content.offset === 0) return { quote: '', body: text }
  return { quote: text.slice(0, content.offset), body: text.slice(content.offset) }
}

/**
 * Lines where a ``$skill-name`` mention is read: every line except quoted
 * context lines and lines inside (or opening/closing) a fenced code block.
 */
function mentionLines(text: string): Array<{ line: string; offset: number }> {
  const lines: Array<{ line: string; offset: number }> = []
  let offset = 0
  let inFence = false
  for (const line of text.split('\n')) {
    const lineOffset = offset
    offset += line.length + 1
    if (FENCE_RE.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence || line.trimStart().startsWith('>')) continue
    lines.push({ line, offset: lineOffset })
  }
  return lines
}

/**
 * Every ``$skill-name`` mention that will activate a Skill.
 *
 * ``skillNames`` holds the user-invocable skills; mentions of unknown names
 * stay plain text. Omit it to fall back to the syntax-only heuristic
 * described above.
 *
 * Hand-rolled instead of a lookbehind regex so the desktop shell's older
 * WebKit builds stay supported.
 */
export function findSkillDirectives(
  text: string,
  skillNames?: ReadonlySet<string>,
): SkillDirectiveRange[] {
  const ranges: SkillDirectiveRange[] = []
  for (const { line, offset } of mentionLines(text)) {
    for (let i = 0; i < line.length; i++) {
      if (line.charAt(i) !== '$') continue
      if (i > 0 && MENTION_HEAD_RE.test(line.charAt(i - 1))) continue
      // The lookahead keeps trailing sentence punctuation ("use $pdf.")
      // out of the name, exactly like the backend.
      const match = MENTION_NAME_RE.exec(line.slice(i + 1))
      if (!match) continue
      const name = match[1]
      const known = skillNames ? skillNames.has(name) : MENTION_HEURISTIC_RE.test(name)
      if (!known) continue
      const end = i + 1 + name.length
      ranges.push({ start: offset + i, end: offset + end, name })
      i = end - 1
    }
  }
  return ranges
}

/**
 * Find the leading ``/command`` when the message opens with one.
 *
 * ``commandNames`` (ids in composer notation, e.g. ``goal`` or
 * ``git:commit``) restricts highlighting to commands that exist, so a typo
 * stays visibly inert while the user is typing. Omit it in the transcript,
 * where the roster that was live at send time is no longer knowable.
 */
export function findCommandDirectives(
  text: string,
  commandNames?: ReadonlySet<string>,
): TokenRange[] {
  const content = firstContentLine(text)
  if (!content) return []
  const { line, offset } = content
  const match = COMMAND_RE.exec(line)
  if (!match) return []
  const name = match[1]
  if (commandNames && !commandNames.has(name) && !commandNames.has(name.replace(':', '/'))) {
    return []
  }
  return [{ start: offset, end: offset + match[0].length, name }]
}

/**
 * The ``$``-token being typed at ``caret``, for the skill picker.
 *
 * Mirrors ``findActiveMention``'s contract: the ``$`` must open a word, the
 * token ends at the next whitespace, and the caret has to sit inside it.
 * Offered on any line where a mention is read — not in quoted context lines
 * or fenced code blocks, where the agent would ignore the inserted token.
 */
export function findActiveSkillToken(
  text: string,
  caret: number,
): { start: number; end: number; query: string } | null {
  const content = mentionLines(text).find(
    ({ line, offset }) => caret >= offset && caret <= offset + line.length,
  )
  if (!content) return null
  const { line, offset } = content

  const local = caret - offset
  let i = local
  while (i > 0) {
    const ch = line.charAt(i - 1)
    if (ch === '$') {
      if (i >= 2 && MENTION_HEAD_RE.test(line.charAt(i - 2))) return null
      return {
        start: offset + i - 1,
        end: caret,
        query: line.slice(i, local),
      }
    }
    if (/\s/.test(ch)) return null
    i--
  }
  return null
}
