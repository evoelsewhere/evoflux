//! The policy behind `access: read-only` agent types (`explore`, `plan`, and
//! any agent file that asks for it): a tool call either only reads, or it is
//! refused before it reaches an approval prompt.
//!
//! * Tools known to be free of side effects pass; the mesh tools (talking to
//!   other agents) pass; every other tool is refused — file writes and also
//!   tools this policy does not know, such as connector tools.
//! * `bash` and `powershell` commands are split into simple commands
//!   (at `;`, `|`, `&&`, newlines, `(`, `)`, `{`, `}` and command
//!   substitutions, so nested commands are checked too) and each must start
//!   with a command on a read-only allow-list, with the options of that
//!   command that write or run programs refused. Output redirection to
//!   anything but the null device is refused; so are here-documents, command
//!   substitution inside double quotes, PowerShell method calls, static .NET
//!   calls, property assignment and the `&` call operator.
//!
//! It is an allow-list: anything it cannot classify is refused, and the
//! refusal says why, so the model can retry with a plainer command.

use serde_json::Value;

/// Tools that only read (or only talk to the person or other agents).
const SAFE_TOOLS: &[&str] = &[
    "read",
    "grep",
    "find",
    "ls",
    "docs",
    "lsp",
    "web_search",
    "web_fetch",
    "ask_user",
    "update_todos",
];

/// Check one tool call of a read-only agent. `Err` is the refusal shown to
/// the model.
pub fn guard(tool: &str, args: &Value) -> Result<(), String> {
    let shell = match tool {
        "bash" => Shell::Bash,
        "powershell" => Shell::PowerShell,
        name if SAFE_TOOLS.contains(&name) || crate::mesh_tools::TOOL_NAMES.contains(&name) => {
            return Ok(())
        }
        name => {
            return Err(format!(
                "Refused: this agent is read-only, and `{name}` can change state."
            ))
        }
    };
    let command = args.get("command").and_then(Value::as_str).unwrap_or("");
    check_command(command, shell).map_err(|reason| {
        format!(
            "Refused: this agent is read-only, and the command {reason}. Use read-only commands \
             (search, list, read, git log/show/diff/status/blame); split a complex command into simple ones."
        )
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Shell {
    Bash,
    PowerShell,
}

/// One word of a simple command.
#[derive(Debug, Clone, Default)]
struct Word {
    /// With quotes removed and their content kept.
    text: String,
    /// The unquoted characters only; each quoted part is a single `"`.
    bare: String,
}

/// `Ok` when every simple command in `command` only reads.
pub fn check_command(command: &str, shell: Shell) -> Result<(), String> {
    for segment in split(command, shell)? {
        check_segment(&segment, shell)?;
    }
    Ok(())
}

/// Targets a redirection may write to: the null device.
fn null_device(target: &str) -> bool {
    matches!(
        target.to_ascii_lowercase().as_str(),
        "/dev/null" | "$null" | "nul" | "/dev/stdout" | "/dev/stderr"
    )
}

/// Characters that end a word.
fn breaks_word(c: char) -> bool {
    c.is_whitespace() || matches!(c, ';' | '|' | '&' | '(' | ')' | '{' | '}' | '<' | '>')
}

/// A PowerShell word just before `(` that names a method (`$x.Delete`,
/// `.Delete` after a parenthesised expression).
fn names_method(word: &str) -> bool {
    word.rfind('.').is_some_and(|dot| {
        let tail = &word[dot + 1..];
        !tail.is_empty() && tail.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
    })
}

/// Split `command` into simple commands (lists of words).
fn split(command: &str, shell: Shell) -> Result<Vec<Vec<Word>>, String> {
    let ps = shell == Shell::PowerShell;
    let escape = if ps { '`' } else { '\\' };
    let chars: Vec<char> = command.chars().collect();
    let n = chars.len();
    let mut segments: Vec<Vec<Word>> = Vec::new();
    let mut words: Vec<Word> = Vec::new();
    let mut word = Word::default();
    let mut in_word = false;

    fn end_word(
        words: &mut Vec<Word>,
        word: &mut Word,
        in_word: &mut bool,
        ps: bool,
    ) -> Result<(), String> {
        if *in_word {
            if ps && word.bare.contains("::") {
                return Err("calls a .NET type member".into());
            }
            words.push(std::mem::take(word));
            *in_word = false;
        }
        Ok(())
    }
    macro_rules! end_word {
        () => {
            end_word(&mut words, &mut word, &mut in_word, ps)?
        };
    }
    macro_rules! end_segment {
        () => {{
            end_word!();
            if !words.is_empty() {
                segments.push(std::mem::take(&mut words));
            }
        }};
    }

    let mut i = 0;
    while i < n {
        let c = chars[i];
        if c == escape {
            match chars.get(i + 1) {
                // Line continuation.
                Some('\n') => i += 2,
                Some(&next) => {
                    word.text.push(next);
                    word.bare.push(next);
                    in_word = true;
                    i += 2;
                }
                None => i += 1,
            }
            continue;
        }
        match c {
            '\'' => {
                i += 1;
                while i < n && chars[i] != '\'' {
                    word.text.push(chars[i]);
                    i += 1;
                }
                if i >= n {
                    return Err("has an unterminated quote".into());
                }
                word.bare.push('"');
                in_word = true;
                i += 1;
            }
            '"' => {
                i += 1;
                loop {
                    let Some(&d) = chars.get(i) else {
                        return Err("has an unterminated quote".into());
                    };
                    if d == '"' {
                        i += 1;
                        break;
                    }
                    if d == escape {
                        if let Some(&next) = chars.get(i + 1) {
                            // Bash keeps a backslash before other characters.
                            if !ps && !matches!(next, '$' | '`' | '"' | '\\' | '\n') {
                                word.text.push('\\');
                            }
                            word.text.push(next);
                            i += 2;
                            continue;
                        }
                    }
                    if (d == '$' && chars.get(i + 1) == Some(&'(')) || (!ps && d == '`') {
                        return Err("runs a command inside a double-quoted string".into());
                    }
                    word.text.push(d);
                    i += 1;
                }
                word.bare.push('"');
                in_word = true;
            }
            '#' if !in_word => {
                while i < n && chars[i] != '\n' {
                    i += 1;
                }
            }
            '\n' | ';' => {
                end_segment!();
                i += 1;
            }
            '|' => {
                end_segment!();
                i += if chars.get(i + 1) == Some(&'|') { 2 } else { 1 };
            }
            '&' if chars.get(i + 1) == Some(&'&') => {
                end_segment!();
                i += 2;
            }
            '&' if !ps && chars.get(i + 1) == Some(&'>') => {
                // `&>file`: both streams to a file.
                end_word!();
                i = redirect(&chars, i + 1)?;
            }
            '&' if ps => return Err("uses the `&` call operator".into()),
            '&' => {
                end_segment!();
                i += 1;
            }
            // `${name}`: a variable, part of the word.
            '{' if word.bare.ends_with('$') => {
                let Some(len) = chars[i..].iter().position(|c| *c == '}') else {
                    return Err("has an unterminated `${`".into());
                };
                let inner: String = chars[i..=i + len].iter().collect();
                if inner.contains("$(") || inner.contains('`') {
                    return Err("runs a command inside a variable expansion".into());
                }
                word.text.push_str(&inner);
                word.bare.push_str(&inner);
                i += len + 1;
            }
            '(' | ')' | '{' | '}' => {
                if ps && c == '(' && names_method(&word.bare) {
                    return Err("calls a method".into());
                }
                end_segment!();
                i += 1;
            }
            '`' if !ps => {
                end_segment!();
                i += 1;
            }
            '>' => {
                // A stream number (`2>`, `*>`) belongs to the redirection.
                if in_word && word.bare.chars().all(|c| c.is_ascii_digit() || c == '*') {
                    word = Word::default();
                    in_word = false;
                } else {
                    end_word!();
                }
                i = redirect(&chars, i)?;
            }
            '<' => {
                if !ps && chars.get(i + 1) == Some(&'<') && chars.get(i + 2) != Some(&'<') {
                    return Err("uses a here-document".into());
                }
                end_word!();
                i += 1;
            }
            c if c.is_whitespace() => {
                end_word!();
                i += 1;
            }
            _ => {
                word.text.push(c);
                word.bare.push(c);
                in_word = true;
                i += 1;
            }
        }
    }
    end_segment!();
    Ok(segments)
}

/// Read the redirection starting at the `>` at `start`; `Err` unless it goes
/// to a stream or the null device. Returns the index after it.
fn redirect(chars: &[char], start: usize) -> Result<usize, String> {
    let mut i = start + 1;
    if matches!(chars.get(i), Some('>' | '|')) {
        i += 1;
    }
    // `>&2`, `2>&1`: into another stream.
    if chars.get(i) == Some(&'&') {
        let digits = chars[i + 1..]
            .iter()
            .take_while(|c| c.is_ascii_digit() || **c == '-')
            .count();
        if digits > 0 {
            return Ok(i + 1 + digits);
        }
        i += 1;
    }
    while chars.get(i).is_some_and(|c| *c == ' ' || *c == '\t') {
        i += 1;
    }
    let mut target = String::new();
    while let Some(&c) = chars.get(i) {
        if breaks_word(c) {
            break;
        }
        if c != '\'' && c != '"' {
            target.push(c);
        }
        i += 1;
    }
    if null_device(&target) {
        Ok(i)
    } else if target.is_empty() {
        Err("redirects output".into())
    } else {
        Err(format!("writes to `{target}` with a redirection"))
    }
}

/// A command word as a plain lowercase name: no folder, no `.exe`.
fn command_name(word: &str) -> String {
    let base = word
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(word)
        .to_ascii_lowercase();
    for suffix in [".exe", ".com"] {
        if let Some(stem) = base.strip_suffix(suffix) {
            return stem.to_string();
        }
    }
    base
}

/// `NAME=` or `NAME+=` at the start of an unquoted word.
fn is_bash_assignment(word: &Word) -> bool {
    let Some(eq) = word.bare.find('=') else {
        return false;
    };
    let name = word.bare[..eq]
        .strip_suffix('+')
        .unwrap_or(&word.bare[..eq]);
    !name.is_empty()
        && !name.starts_with(|c: char| c.is_ascii_digit())
        && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn check_segment(words: &[Word], shell: Shell) -> Result<(), String> {
    match shell {
        Shell::Bash => check_bash(words),
        Shell::PowerShell => check_powershell(words),
    }
}

fn check_bash(mut words: &[Word]) -> Result<(), String> {
    while let Some(first) = words.first() {
        match first.bare.as_str() {
            "!" | "then" | "do" | "else" | "elif" | "if" | "while" | "until" | "time" => {
                words = &words[1..]
            }
            // Loop and case headers: the words are values, not commands.
            "for" | "select" | "case" | "in" | "done" | "fi" | "esac" | ";;" => return Ok(()),
            _ if is_bash_assignment(first) => words = &words[1..],
            _ => break,
        }
    }
    let Some(first) = words.first() else {
        return Ok(());
    };
    let name = command_name(&first.text);
    let args = &words[1..];
    match name.as_str() {
        "cd" | "pushd" | "popd" | "true" | "false" | ":" | "test" | "[" | "[[" | "]]" | "read"
        | "pwd" | "export" | "local" | "declare" | "unset" | "set" | "shopt" | "exit"
        | "return" | "break" | "continue" | "type" | "sleep" | "wait" => Ok(()),
        "command"
            if args
                .first()
                .is_some_and(|a| a.text == "-v" || a.text == "-V") =>
        {
            Ok(())
        }
        _ => check_native(&name, args),
    }
}

/// PowerShell cmdlets and aliases that only read or format.
const POWERSHELL_SAFE: &[&str] = &[
    "get-childitem",
    "gci",
    "ls",
    "dir",
    "get-content",
    "gc",
    "cat",
    "type",
    "select-string",
    "sls",
    "get-item",
    "gi",
    "get-itemproperty",
    "gp",
    "test-path",
    "resolve-path",
    "rvpa",
    "get-location",
    "gl",
    "pwd",
    "measure-object",
    "measure",
    "select-object",
    "select",
    "where-object",
    "where",
    "?",
    "sort-object",
    "sort",
    "group-object",
    "group",
    "format-table",
    "ft",
    "format-list",
    "fl",
    "format-wide",
    "fw",
    "out-string",
    "out-null",
    "out-host",
    "convertto-json",
    "convertfrom-json",
    "convertto-csv",
    "convertfrom-csv",
    "write-output",
    "echo",
    "write",
    "write-host",
    "get-command",
    "gcm",
    "get-member",
    "gm",
    "get-date",
    "get-filehash",
    "split-path",
    "join-path",
    "compare-object",
    "diff",
    "compare",
    "get-process",
    "gps",
    "ps",
    "select-xml",
    "get-acl",
    "get-alias",
    "get-variable",
    "get-psdrive",
    "get-unique",
    "set-location",
    "cd",
    "sl",
    "push-location",
    "pushd",
    "pop-location",
    "popd",
];

fn check_powershell(mut words: &[Word]) -> Result<(), String> {
    while let Some(first) = words.first() {
        match first.bare.to_ascii_lowercase().as_str() {
            // Alone, `foreach` is the ForEach-Object alias (checked below).
            "foreach" if words.len() > 1 => words = &words[1..],
            "if" | "else" | "elseif" | "for" | "while" | "do" | "switch" | "try" | "catch"
            | "finally" | "return" | "break" | "continue" | "throw" => words = &words[1..],
            _ => break,
        }
    }
    let Some(first) = words.first() else {
        return Ok(());
    };
    // An assignment (`$x = …`) or a hashtable entry (`n = 'Size'`).
    if let Some(index) = words.iter().position(|w| w.bare.contains('=')) {
        if first.bare.starts_with(['$', '.']) || (index == 0 && !first.bare.starts_with('-')) {
            let eq = words[index].bare.find('=').unwrap_or(0);
            let target: String = words[..index]
                .iter()
                .map(|w| w.bare.as_str())
                .chain([&words[index].bare[..eq]])
                .collect();
            if target.contains('.') || target.contains('[') {
                return Err("sets a property".into());
            }
            let rest = words[index].bare[eq + 1..].trim_start_matches(['=', '+', '-', '*', '/']);
            let mut value: Vec<Word> = Vec::new();
            if !rest.is_empty() {
                value.push(Word {
                    text: rest.to_string(),
                    bare: rest.to_string(),
                });
            }
            value.extend(words[index + 1..].iter().cloned());
            return match value.first() {
                Some(w) if w.bare.starts_with(|c: char| c.is_ascii_alphabetic()) => {
                    check_powershell(&value)
                }
                _ => Ok(()),
            };
        }
    }
    let lead = first.bare.chars().next().unwrap_or('"');
    // Expressions and operators: variables, literals, casts, `-not`, `!`,
    // and a property of a parenthesised expression (`(…).Count`; a method
    // call was refused while splitting). `. file` (dot-sourcing) is not one.
    let property = lead == '.' && first.bare[1..].starts_with(|c: char| c.is_ascii_alphabetic());
    if property
        || matches!(lead, '$' | '"' | '@' | '[' | '-' | '!' | ',' | '+')
        || lead.is_ascii_digit()
    {
        return Ok(());
    }
    let name = command_name(&first.text);
    let args = &words[1..];
    if matches!(name.as_str(), "foreach-object" | "%" | "foreach") {
        // A bare word names a member to call on each item (`% Delete`).
        return match args.iter().find(|a| {
            !matches!(
                a.bare.to_ascii_lowercase().as_str(),
                "-process" | "-begin" | "-end"
            )
        }) {
            Some(arg) => Err(format!("calls `{}` on each item", arg.text)),
            None => Ok(()),
        };
    }
    if POWERSHELL_SAFE.contains(&name.as_str()) {
        return Ok(());
    }
    check_native(&name, args)
}

/// Programs that only read, whatever their arguments (except as noted).
const NATIVE_SAFE: &[&str] = &[
    "cat",
    "head",
    "tail",
    "ls",
    "dir",
    "pwd",
    "echo",
    "printf",
    "wc",
    "cut",
    "tr",
    "nl",
    "column",
    "file",
    "stat",
    "du",
    "df",
    "which",
    "whereis",
    "where",
    "basename",
    "dirname",
    "realpath",
    "readlink",
    "grep",
    "egrep",
    "fgrep",
    "diff",
    "cmp",
    "comm",
    "jq",
    "date",
    "whoami",
    "uname",
    "hostname",
    "id",
    "printenv",
    "ps",
    "tac",
    "rev",
    "fold",
    "paste",
    "join",
    "seq",
    "expr",
    "strings",
    "od",
    "hexdump",
    "md5sum",
    "sha1sum",
    "sha256sum",
    "findstr",
    "true",
    "false",
];

fn check_native(name: &str, args: &[Word]) -> Result<(), String> {
    let has = |flags: &[&str]| {
        args.iter().find(|a| {
            flags
                .iter()
                .any(|f| a.text == *f || a.text.starts_with(&format!("{f}=")))
        })
    };
    let refuse = |arg: &Word| {
        Err(format!(
            "passes `{name}` the option `{}`, which writes or runs a program",
            arg.text
        ))
    };
    match name {
        _ if NATIVE_SAFE.contains(&name) => Ok(()),
        "sort" => has(&["-o", "--output"]).map_or(Ok(()), refuse),
        "tree" => has(&["-o"]).map_or(Ok(()), refuse),
        "rg" => has(&["--pre"]).map_or(Ok(()), refuse),
        "fd" | "fdfind" => has(&["-x", "-X", "--exec", "--exec-batch"]).map_or(Ok(()), refuse),
        "find" => has(&[
            "-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
            "-fls",
        ])
        .map_or(Ok(()), refuse),
        // A second file operand is an output file.
        "uniq" if args.iter().filter(|a| !a.text.starts_with('-')).count() > 1 => {
            Err("passes `uniq` an output file".into())
        }
        "uniq" => Ok(()),
        "git" => check_git(args),
        _ => Err(format!("runs `{name}`, which is not on the read-only list")),
    }
}

/// Git subcommands that only read.
const GIT_READ: &[&str] = &[
    "log",
    "show",
    "diff",
    "status",
    "blame",
    "annotate",
    "grep",
    "ls-files",
    "ls-tree",
    "rev-parse",
    "rev-list",
    "cat-file",
    "describe",
    "shortlog",
    "merge-base",
    "name-rev",
    "show-ref",
    "for-each-ref",
    "whatchanged",
    "count-objects",
    "check-ignore",
    "check-attr",
    "diff-tree",
    "diff-files",
    "diff-index",
    "version",
    "var",
    "show-branch",
    "cherry",
    "range-diff",
];

fn check_git(args: &[Word]) -> Result<(), String> {
    let mut i = 0;
    while let Some(arg) = args.get(i).filter(|a| a.text.starts_with('-')) {
        let text = arg.text.as_str();
        match text {
            "--no-pager"
            | "-P"
            | "--no-optional-locks"
            | "--literal-pathspecs"
            | "--no-replace-objects" => i += 1,
            "-C" => i += 2,
            _ if text.starts_with("--git-dir=") || text.starts_with("--work-tree=") => i += 1,
            // `-c` can point a pager or diff driver at any program.
            _ => return Err(format!("passes git the option `{text}`")),
        }
    }
    let Some(sub) = args.get(i) else {
        return Ok(());
    };
    let sub = sub.text.as_str();
    let rest = &args[i + 1..];
    let flag = |a: &Word| a.text.split('=').next().unwrap_or("").to_string();
    let any = |names: &[&str]| rest.iter().any(|a| names.contains(&flag(a).as_str()));
    let first_operand = rest
        .iter()
        .find(|a| !a.text.starts_with('-'))
        .map(|a| a.text.as_str());
    if let Some(arg) = rest.iter().find(|a| flag(a) == "--output") {
        return Err(format!(
            "passes git the option `{}`, which writes a file",
            arg.text
        ));
    }
    let refuse = || {
        Err(format!(
            "runs `git {sub}` in a way that can change the repository"
        ))
    };
    match sub {
        "grep" if any(&["-O", "--open-files-in-pager"]) => refuse(),
        _ if GIT_READ.contains(&sub) => Ok(()),
        "branch" | "tag" => {
            let listing: &[&str] = &[
                "-a",
                "--all",
                "-r",
                "--remotes",
                "-v",
                "-vv",
                "--verbose",
                "-l",
                "--list",
                "--show-current",
                "--contains",
                "--no-contains",
                "--merged",
                "--no-merged",
                "--points-at",
                "--sort",
                "--format",
                "--color",
                "--no-color",
                "--column",
                "--no-column",
                "-i",
                "--ignore-case",
                "--abbrev",
                "--no-abbrev",
                "-n",
            ];
            let flags_ok = rest.iter().filter(|a| a.text.starts_with('-')).all(|a| {
                let f = flag(a);
                listing.contains(&f.as_str())
                    || (f.starts_with("-n") && f[2..].chars().all(|c| c.is_ascii_digit()))
            });
            // Without a listing option, a name creates a branch or tag.
            let lists = any(&[
                "-l",
                "--list",
                "--contains",
                "--no-contains",
                "--merged",
                "--no-merged",
                "--points-at",
                "--sort",
                "--format",
            ]);
            if flags_ok && (first_operand.is_none() || lists) {
                Ok(())
            } else {
                refuse()
            }
        }
        "remote" => match first_operand {
            None | Some("show" | "get-url") => Ok(()),
            _ => refuse(),
        },
        "stash" | "notes" => match first_operand {
            Some("list" | "show") => Ok(()),
            _ => refuse(),
        },
        "reflog" => match first_operand {
            None | Some("show") => Ok(()),
            _ => refuse(),
        },
        "worktree" if first_operand == Some("list") => Ok(()),
        "submodule" if first_operand == Some("status") => Ok(()),
        "config" => {
            let writes = any(&[
                "--add",
                "--unset",
                "--unset-all",
                "--replace-all",
                "--rename-section",
                "--remove-section",
                "-e",
                "--edit",
            ]);
            let reads = matches!(first_operand, Some("get" | "list"))
                || any(&[
                    "--get",
                    "--get-all",
                    "--get-regexp",
                    "--get-urlmatch",
                    "--list",
                    "-l",
                ]);
            if reads && !writes {
                Ok(())
            } else {
                refuse()
            }
        }
        _ => refuse(),
    }
}

#[cfg(test)]
mod tests;
