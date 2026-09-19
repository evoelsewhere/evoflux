/**
 * Workspace path utilities.
 *
 * Windows extended-length paths (``//?/C:/…`` or ``\\?\C:\…``) are used by the
 * OS to bypass the legacy 260-character ``MAX_PATH`` limit.  The Python backend
 * and Rust Tauri layer both handle these prefixes transparently, but when the
 * path is passed through a URL query parameter the Tauri webview can mangle it,
 * producing an HTTP 400.
 *
 * The fix: strip the prefix at the point the path enters the frontend HTTP
 * layer.  The backend re-resolves the normalised path, so the prefix is not
 * required for correctness.
 */

/** Regex matching the Windows extended-length path prefix variants. */
const EXTENDED_PATH_RE = /^[/\\]{2}\?[/\\]/

/**
 * Strip the ``//?/`` or ``\\?\`` Windows extended-length path prefix, if
 * present.  Returns the unchanged string on other platforms or when the prefix
 * is absent.
 *
 * @example
 * stripExtendedPathPrefix("//?/C:/Users") // "C:/Users"
 * stripExtendedPathPrefix("\\\\?\\C:\\Users") // "C:\\Users"
 * stripExtendedPathPrefix("/home/user") // "/home/user"
 */
export function stripExtendedPathPrefix(p: string): string {
  return p.replace(EXTENDED_PATH_RE, '')
}
