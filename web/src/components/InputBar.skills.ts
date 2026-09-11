/**
 * Composer token grammar — the single source of truth for which
 * ``/command``, ``/skill:<name>`` and ``$<name>`` substrings are *live*
 * directives rather than plain prose.
 *
 * Both the composer overlay (while typing) and the transcript renderer
 * (after send) use these helpers, so a token looks the same before and
 * after the message leaves the input.
 *
 * The rules mirror what actually consumes each token on the way out:
 *
 *   - ``$name`` / ``/skill:name`` — ``ExplicitSkillSelectionHook``
 *     (app/agent/hooks/explicit_skill_selection.py) reads **one** selector
 *     per message: it walks past composer quote lines, then inspects the
 *     first real content line only. A slash directive must open that line;
 *     a ``$`` directive may sit anywhere in it. Directives further down the
 *     message are inert, so they stay unhighlighted here too.
 *   - ``/command`` — the front-end interceptors (``parseGoalCommand``,
 *     ``parseWorkflowCommand``, ``expandUserCommand``) all test the trimmed
 *     message's first token, so only a leading command is live.
 */

/** Skill / command name: ``audit-runtime`` or one level of ``git:commit``. */
const NAME = '[a-zA-Z0-9][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?'
const SLASH_SKILL_RE = new RegExp(`^/skill:(${NAME})(?=\\s|$)`)
const COMMAND_RE = new RegExp(`^/(?!skill:)(${NAME})(?=\\s|$)`)
/**
 * Heuristic used when no skill roster is available (the transcript renders
 * old messages without querying the skill list): the name must start with a
 * lowercase letter and be at least two characters. That keeps ``$5``,
 * ``$100`` and command placeholders like ``$ARGUMENTS`` out of the
 * highlighter while still catching real kebab-case skill names.
 */
const DOLLAR_HEURISTIC_RE = /^[a-z][a-zA-Z0-9._-]*(?::[a-zA-Z0-9][a-zA-Z0-9._-]*)?$/
/** ``$name`` body plus the backend's terminator lookahead. */
const DOLLAR_NAME_RE = new RegExp(`^(${NAME})(?=[\\s.,!?;:]|$)`)
/** A ``$`` glued to one of these is part of a word/variable, not a directive. */
const DOLLAR_HEAD_RE = /[a-zA-Z0-9_$]/

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
 * and blank lines are skipped, exactly as the backend hook does.
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

function isKnownSkill(name: string, skillNames?: ReadonlySet<string>): boolean {
  if (!skillNames) return true
  return skillNames.has(name) || skillNames.has(name.replace(':', '/'))
}

/**
 * Find the one skill directive that will actually activate a skill.
 *
 * Accepts both composer notations — ``/skill:<name>`` opening the first
 * content line, and ``$<name>`` anywhere inside it. Returns an array (never
 * more than one entry) so callers can concatenate it with the other range
 * lists without special-casing.
 *
 * ``skillNames`` holds the invocable skills in composer notation (flat or
 * ``parent:sub``); unknown directives stay plain text. Omit it to fall back
 * to the syntax-only heuristic described above.
 */
export function findSkillDirectives(
  text: string,
  skillNames?: ReadonlySet<string>,
): SkillDirectiveRange[] {
  const content = firstContentLine(text)
  if (!content) return []
  const { line, offset } = content

  // A slash directive wins the line outright — the backend never falls
  // through to ``$`` once ``^/skill:`` matched.
  const slash = SLASH_SKILL_RE.exec(line)
  if (slash) {
    const name = slash[1]
    if (!isKnownSkill(name, skillNames)) return []
    return [{ start: offset, end: offset + slash[0].length, name }]
  }

  const dollar = findDollarDirective(line, skillNames)
  if (!dollar) return []
  return [{
    start: offset + dollar.start,
    end: offset + dollar.end,
    name: dollar.name,
  }]
}

/**
 * First ``$name`` in ``line`` that reads as a directive rather than as a
 * price, a shell variable or a ``$ARGUMENTS`` placeholder.
 *
 * Hand-rolled instead of a lookbehind regex so the desktop shell's older
 * WebKit builds stay supported.
 */
function findDollarDirective(
  line: string,
  skillNames?: ReadonlySet<string>,
): TokenRange | null {
  for (let i = 0; i < line.length; i++) {
    if (line.charAt(i) !== '$') continue
    if (i > 0 && DOLLAR_HEAD_RE.test(line.charAt(i - 1))) continue
    // The lookahead makes the engine backtrack off trailing sentence
    // punctuation ("use $work-writing." keeps the period out of the name)
    // while leaving a nested ``git:commit`` intact.
    const match = DOLLAR_NAME_RE.exec(line.slice(i + 1))
    if (!match) continue
    const name = match[1]
    const end = i + 1 + name.length
    if (skillNames) {
      if (!isKnownSkill(name, skillNames)) continue
    } else if (!DOLLAR_HEURISTIC_RE.test(name)) {
      continue
    }
    return { start: i, end, name }
  }
  return null
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
 * Restricted to the first content line because that is the only place a
 * skill directive is read — offering the picker anywhere else would insert
 * a token the agent silently ignores.
 */
export function findActiveSkillToken(
  text: string,
  caret: number,
): { start: number; end: number; query: string } | null {
  const content = firstContentLine(text)
  if (!content) return null
  const { line, offset } = content
  if (caret < offset || caret > offset + line.length) return null

  const local = caret - offset
  let i = local
  while (i > 0) {
    const ch = line.charAt(i - 1)
    if (ch === '$') {
      if (i >= 2 && DOLLAR_HEAD_RE.test(line.charAt(i - 2))) return null
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
