type AmdDefineGlobal = { define?: unknown }

/**
 * Monaco's editor loads through its AMD loader, which installs a global
 * `define` (a `var`-declared global: non-configurable but writable).
 * Mermaid's pre-bundled UMD dependencies detect that `define`, register
 * anonymously, and the loader throws "Can only have one anonymous define
 * call per script file" — failing the whole render. Clear the global for the
 * duration of mermaid's import+render and restore it afterwards; monaco only
 * needs it while its own plugin scripts execute.
 */
// Renders can overlap, so the hide is reference-counted: the first render
// saves and clears `define`, the last one to finish restores it.
let amdHideDepth = 0
let amdSavedDefine: unknown

export async function withAmdDefineHidden<T>(run: () => Promise<T>): Promise<T> {
  const scope = globalThis as AmdDefineGlobal
  if (amdHideDepth === 0) {
    const savedDefine = scope.define
    if (typeof savedDefine !== 'function') return run()
    try {
      scope.define = undefined
    } catch {
      return run()
    }
    if (scope.define !== undefined) return run() // read-only in this environment
    amdSavedDefine = savedDefine
  }
  amdHideDepth += 1
  try {
    return await run()
  } finally {
    amdHideDepth -= 1
    if (amdHideDepth === 0) scope.define = amdSavedDefine
  }
}
