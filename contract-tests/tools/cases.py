"""Fixture workspaces and cases shared by the Python and Rust tool parity runs.

``build()`` returns the fixtures (files written into a workspace, plus a sibling
``outside`` directory) and the list of cases. ``cases.json`` is this value
serialised so the Rust tests read the same data (it lives with the crate, as
``cargo mutants`` copies only ``server/``); ``test_tools.py`` checks the two
agree. ``golden.json`` beside it holds what the Python tools answered.

Placeholders in ``args``: ``<WS>`` is the absolute workspace path and
``<OUT>`` the absolute path of the directory beside it.
"""

from __future__ import annotations

import base64
from typing import Any

MTIME_BASE = 1_700_000_000
GI_RULES = (
    "*.tmp\n/top.txt\nsub/inner.txt\n**/gen/\na*b\n[xy].dat\ndir.d/\n"
    " spaced.txt \n# not.txt\n\\#hash.txt\n"
)


def _text(content: str, mtime: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"text": content}
    if mtime is not None:
        entry["mtime"] = mtime
    return entry


def _bytes(content: bytes) -> dict[str, Any]:
    return {"b64": base64.b64encode(content).decode("ascii")}


def _numbered(count: int, template: str) -> str:
    return "".join(template.format(n=n) + "\n" for n in range(1, count + 1))


def _files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {
        "README.md": _text(
            "# Demo project\n\nA TODO list lives here.\nSecond TODO line.\n"
            "Unicode: café ✓ naïve\n\n## Usage\n\nrun `make`\n\n## License\nMIT\n"
        ),
        "src/main.py": _text(
            "import os\n\n\ndef main():\n    # TODO: wire up\n    print('hello')\n\n\n"
            "if __name__ == '__main__':\n    main()\n"
        ),
        "src/util.py": _text(
            "def helper(x):\n    return x * 2\n\n\nclass Thing:\n    def run(self):\n"
            "        return helper(2)\n"
        ),
        "src/lib/helpers.py": _text("HELPER = 1\n# TODO later\n"),
        "src/app.ts": _text(
            "export function app() {\n  return 'app';\n}\n// TODO: types\n"
        ),
        "src/app.test.ts": _text("test('app', () => {});\n"),
        "docs/guide.md": _text("# Guide\n\nSee the TODO list.\n"),
        "docs/notes.txt": _text("note one\nnote two\n"),
        "crlf.txt": _bytes(b"one\r\ntwo\r\nthree\r\n"),
        "cr_only.txt": _bytes(b"one\rtwo\rthree"),
        "latin1.txt": _bytes(b"caf\xe9 au lait\n"),
        "bom.txt": _bytes(b"\xef\xbb\xbfbom line\n"),
        "blank.txt": _text(""),
        "nonl.txt": _text("first\nlast without newline"),
        "sep.txt": _text("a\x0cb\u2028c\nd\n"),
        "big.txt": _text(("x" * 25_000) + "\nsecond line\n"),
        "long_lines.txt": _text(("L" * 300) + " needle tail\nshort needle\n"),
        "lines.txt": _text(_numbered(250, "line {n} match")),
        "pic.png": _bytes(bytes(range(256)) * 8),
        "doc.docx": _bytes(b"PK\x03\x04" + b"0" * 1500),
        "data.bin": _bytes(b"\xff\xfe\x00\x01 needle \xff"),
        "name with spaces.txt": _text("spaced needle\n"),
        "ünïcode.txt": _text("unicode needle\n"),
        "file.with.dots.tar.gz": _text("not really gzip\n"),
        ".env": _text("SECRET=1\n"),
        ".env.local": _text("SECRET=2\n"),
        ".envrc": _text("export A=1\n"),
        ".hidden/secret.txt": _text("hidden needle\n"),
        "dotdir/.dotfile": _text("dotfile needle\n"),
        "node_modules/pkg/index.js": _text("module.exports = 'needle';\n"),
        "dist/bundle.js": _text("needle\n"),
        "build/out.txt": _text("needle\n"),
        "venv/x.py": _text("needle = 1\n"),
        "__pycache__/m.pyc": _text("needle\n"),
        "nested/node_modules/deep.txt": _text("needle\n"),
        "nested/build": _text("a file named build needle\n"),
        "nested/ok.txt": _text("nested needle\n"),
        "ign/.gitignore": _text(
            "*.log\nbuild/\nignored_dir/\n/rooted.txt\n# comment\n\ndocs/*.tmp\n"
        ),
        "ign/keep.txt": _text("needle keep\n"),
        "ign/app.log": _text("needle log\n"),
        "ign/rooted.txt": _text("needle rooted\n"),
        "ign/sub/rooted.txt": _text("needle sub rooted\n"),
        "ign/sub/trace.log": _text("needle sub log\n"),
        "ign/build/out.txt": _text("needle build\n"),
        "ign/ignored_dir/x.txt": _text("needle ignored\n"),
        "ign/docs/a.tmp": _text("needle tmp\n"),
        "ign/docs/a.txt": _text("needle doc\n"),
        "neg/.gitignore": _text("*.log\n!keep.log\nout/\n"),
        "neg/a.log": _text("needle a\n"),
        "neg/keep.log": _text("needle keep\n"),
        "neg/out/x.txt": _text("needle out\n"),
        "neg/b.txt": _text("needle b\n"),
        "gi_a/.gitignore": _text(GI_RULES),
        "gi_b/.gitignore": _text(GI_RULES + "!sub/inner.txt\n!a.tmp\n"),
        "gi_a/top.txt": _text("x\n"),
        "gi_a/sub/top.txt": _text("x\n"),
        "gi_a/sub/inner.txt": _text("x\n"),
        "gi_a/x/sub/inner.txt": _text("x\n"),
        "gi_a/gen/a.txt": _text("x\n"),
        "gi_a/p/gen/b.txt": _text("x\n"),
        "gi_a/axb": _text("x\n"),
        "gi_a/a/xb": _text("x\n"),
        "gi_a/a.tmp": _text("x\n"),
        "gi_a/sub/b.tmp": _text("x\n"),
        "gi_a/x.dat": _text("x\n"),
        "gi_a/z.dat": _text("x\n"),
        "gi_a/dir.d/f.txt": _text("x\n"),
        "gi_a/spaced.txt": _text("x\n"),
        "gi_a/#hash.txt": _text("x\n"),
        "gi_a/not.txt": _text("x\n"),
        "gi_a/keep.txt": _text("x\n"),
        "gi_b/top.txt": _text("x\n"),
        "gi_b/sub/top.txt": _text("x\n"),
        "gi_b/sub/inner.txt": _text("x\n"),
        "gi_b/x/sub/inner.txt": _text("x\n"),
        "gi_b/gen/a.txt": _text("x\n"),
        "gi_b/p/gen/b.txt": _text("x\n"),
        "gi_b/axb": _text("x\n"),
        "gi_b/a/xb": _text("x\n"),
        "gi_b/a.tmp": _text("x\n"),
        "gi_b/sub/b.tmp": _text("x\n"),
        "gi_b/x.dat": _text("x\n"),
        "gi_b/z.dat": _text("x\n"),
        "gi_b/dir.d/f.txt": _text("x\n"),
        "gi_b/spaced.txt": _text("x\n"),
        "gi_b/#hash.txt": _text("x\n"),
        "gi_b/not.txt": _text("x\n"),
        "gi_b/keep.txt": _text("x\n"),
        "multi.txt": _text("alpha\nbeta\ngamma\ndelta\nalpha beta\n"),
        "ctx.txt": _text(
            "one\ntwo\nHIT a\nthree\nfour\nfive\nsix\nseven\nHIT b\neight\nHIT c\nnine\n"
        ),
        "case.txt": _text("Needle\nNEEDLE\nneedle\n"),
        "regex.txt": _text("a.b\naxb\nfoo(bar)\nfoo bar\nfoofoo\n"),
    }
    for n in range(1, 31):
        files[f"many/f{n:02d}.txt"] = _text(
            f"many {n}\n", MTIME_BASE + 100_000 + n * 60
        )
    # Two files with the same mtime: the path breaks the tie.
    files["ties/b.txt"] = _text("tie\n", MTIME_BASE + 500_000)
    files["ties/a.txt"] = _text("tie\n", MTIME_BASE + 500_000)
    files["ties/c.txt"] = _text("tie\n", MTIME_BASE + 500_001)
    return files


def _case(
    case_id: str,
    tool: str,
    args: dict[str, Any] | None = None,
    **flags: Any,
) -> dict[str, Any]:
    return {"id": case_id, "tool": tool, "args": args or {}, **flags}


def _cases() -> list[dict[str, Any]]:
    c = _case
    cases: list[dict[str, Any]] = []

    # ── read ─────────────────────────────────────────────────────────────
    cases += [
        c("read/readme", "read", {"path": "README.md"}),
        c("read/nested", "read", {"path": "src/main.py"}),
        c("read/abs-inside", "read", {"path": "<WS>/src/main.py"}, normalize=True),
        c("read/dot-slash", "read", {"path": "./src/../src/util.py"}),
        c("read/crlf", "read", {"path": "crlf.txt"}),
        c("read/cr-only", "read", {"path": "cr_only.txt"}),
        c("read/latin1", "read", {"path": "latin1.txt"}),
        c("read/bom", "read", {"path": "bom.txt"}),
        c("read/blank", "read", {"path": "blank.txt"}),
        c("read/no-trailing-newline", "read", {"path": "nonl.txt"}),
        c("read/separators-whole", "read", {"path": "sep.txt"}),
        c(
            "read/separators-paged",
            "read",
            {"path": "sep.txt", "offset": 2, "limit": 2},
        ),
        c("read/truncated", "read", {"path": "big.txt"}),
        c("read/truncated-paged", "read", {"path": "big.txt", "offset": 1, "limit": 1}),
        c("read/page-middle", "read", {"path": "lines.txt", "offset": 100, "limit": 5}),
        c("read/page-from-offset", "read", {"path": "lines.txt", "offset": 248}),
        c("read/page-limit-only", "read", {"path": "lines.txt", "limit": 3}),
        c(
            "read/page-offset-one-limit",
            "read",
            {"path": "lines.txt", "offset": 1, "limit": 2},
        ),
        c(
            "read/page-offset-zero",
            "read",
            {"path": "lines.txt", "offset": 0, "limit": 2},
        ),
        c(
            "read/page-offset-negative",
            "read",
            {"path": "lines.txt", "offset": -7, "limit": 2},
        ),
        c(
            "read/page-past-end",
            "read",
            {"path": "lines.txt", "offset": 999, "limit": 5},
        ),
        c(
            "read/page-limit-zero",
            "read",
            {"path": "lines.txt", "offset": 2, "limit": 0},
        ),
        c(
            "read/page-limit-negative",
            "read",
            {"path": "lines.txt", "offset": 2, "limit": -1},
        ),
        c(
            "read/page-limit-very-negative",
            "read",
            {"path": "lines.txt", "offset": 2, "limit": -999},
        ),
        c(
            "read/page-string-numbers",
            "read",
            {"path": "lines.txt", "offset": "3", "limit": "2"},
        ),
        c(
            "read/page-float-numbers",
            "read",
            {"path": "lines.txt", "offset": 3.0, "limit": 2.0},
        ),
        c(
            "read/page-bool-offset",
            "read",
            {"path": "lines.txt", "offset": True, "limit": 1},
        ),
        c(
            "read/limit-null",
            "read",
            {"path": "lines.txt", "limit": None, "offset": 249},
        ),
        c("read/image", "read", {"path": "pic.png"}),
        c("read/office", "read", {"path": "doc.docx"}),
        c("read/binary-as-text", "read", {"path": "data.bin"}),
        c("read/missing", "read", {"path": "nope.txt"}),
        c("read/missing-nested", "read", {"path": "src/nope/deeper.py"}),
        c("read/directory", "read", {"path": "src"}),
        c("read/dot", "read", {"path": "."}, normalize=True),
        c("read/spaces", "read", {"path": "name with spaces.txt"}),
        c("read/unicode-name", "read", {"path": "ünïcode.txt"}),
        c("read/denied-env", "read", {"path": ".env"}, normalize=True),
        c("read/denied-env-local", "read", {"path": ".env.local"}, normalize=True),
        c(
            "read/denied-env-nested-missing",
            "read",
            {"path": "sub/.env"},
            normalize=True,
        ),
        c("read/allowed-envrc", "read", {"path": ".envrc"}),
        # Windows resolves these to `.env` before the deny pattern runs.
        c(
            "read/denied-env-stream",
            "read",
            {"path": ".env::$DATA"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "read/denied-env-trailing-dot",
            "read",
            {"path": ".env."},
            only_os="windows",
            normalize=True,
        ),
        c(
            "read/denied-env-upper",
            "read",
            {"path": ".ENV"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "read/denied-env-local-upper",
            "read",
            {"path": ".ENV.LOCAL"},
            only_os="windows",
            normalize=True,
        ),
        c("read/hidden-dir-file", "read", {"path": ".hidden/secret.txt"}),
        c("read/file-as-directory", "read", {"path": "README.md/inner.txt"}),
    ]

    # ── ls ───────────────────────────────────────────────────────────────
    cases += [
        c("ls/default", "ls"),
        c("ls/dot", "ls", {"path": "."}),
        c("ls/src", "ls", {"path": "src"}),
        c("ls/src-slash", "ls", {"path": "src/"}),
        c("ls/many", "ls", {"path": "many"}),
        c("ls/ties", "ls", {"path": "ties"}),
        c("ls/abs-inside", "ls", {"path": "<WS>/docs"}, normalize=True),
        c("ls/empty", "ls", {"path": "empty_dir"}),
        c("ls/missing", "ls", {"path": "nope"}),
        c("ls/file", "ls", {"path": "README.md"}),
        c("ls/hidden", "ls", {"path": ".hidden"}),
        c("ls/dotdir", "ls", {"path": "dotdir"}),
        c("ls/ign", "ls", {"path": "ign"}),
    ]

    # ── glob ─────────────────────────────────────────────────────────────
    g = "glob"
    cases += [
        c("glob/py-recursive", g, {"pattern": "**/*.py"}),
        c("glob/py-src", g, {"pattern": "src/**/*.py"}),
        c("glob/py-top", g, {"pattern": "*.py"}),
        c("glob/ts-src", g, {"pattern": "src/*.ts"}),
        c("glob/ts-dot-test", g, {"pattern": "**/*.test.ts"}),
        c("glob/txt-recursive", g, {"pattern": "**/*.txt"}),
        c("glob/name-txt", g, {"pattern": "*.txt", "match": "name"}),
        c("glob/name-py", g, {"pattern": "*.py", "match": "name"}),
        c("glob/name-question", g, {"pattern": "f0?.txt", "match": "name"}),
        c("glob/name-class", g, {"pattern": "f[0-1]?.txt", "match": "name"}),
        c("glob/name-negated-class", g, {"pattern": "f[!0]?.txt", "match": "name"}),
        c("glob/name-exact", g, {"pattern": "util.py", "match": "name"}),
        c("glob/name-no-match", g, {"pattern": "*.zzz", "match": "name"}),
        c("glob/path-no-match", g, {"pattern": "**/*.zzz"}),
        c("glob/in-directory", g, {"pattern": "*.py", "directory": "src"}),
        c(
            "glob/in-directory-name",
            g,
            {"pattern": "*.ts", "directory": "src", "match": "name"},
        ),
        c(
            "glob/in-directory-abs",
            g,
            {"pattern": "*.md", "directory": "<WS>/docs"},
            normalize=True,
        ),
        c("glob/dot-file-skipped", g, {"pattern": ".*", "match": "name"}),
        c("glob/dot-pattern-path", g, {"pattern": ".hidden/*.txt"}),
        c("glob/star-star-all", g, {"pattern": "**/*", "max_results": 1000}),
        c("glob/skips-generated", g, {"pattern": "**/*.js"}),
        c("glob/skips-generated-name", g, {"pattern": "*.js", "match": "name"}),
        c("glob/file-named-build", g, {"pattern": "**/build"}),
        c("glob/multi-dots", g, {"pattern": "*.gz", "match": "name"}),
        c("glob/name-with-spaces", g, {"pattern": "name*", "match": "name"}),
        c("glob/unicode", g, {"pattern": "ünï*", "match": "name"}),
        c("glob/page-first", g, {"pattern": "many/*.txt", "max_results": 5}),
        c(
            "glob/page-second",
            g,
            {"pattern": "many/*.txt", "max_results": 5, "offset": 5},
        ),
        c(
            "glob/page-last",
            g,
            {"pattern": "many/*.txt", "max_results": 10, "offset": 25},
        ),
        c("glob/page-exact-end", g, {"pattern": "many/*.txt", "max_results": 30}),
        c("glob/page-past-end", g, {"pattern": "many/*.txt", "offset": 99}),
        c(
            "glob/page-name-mode",
            g,
            {"pattern": "f*.txt", "match": "name", "max_results": 4, "offset": 2},
        ),
        c("glob/page-limit-zero", g, {"pattern": "many/*.txt", "max_results": 0}),
        c("glob/page-limit-negative", g, {"pattern": "many/*.txt", "max_results": -5}),
        c(
            "glob/page-offset-negative",
            g,
            {"pattern": "many/*.txt", "max_results": 2, "offset": -4},
        ),
        c(
            "glob/page-string-numbers",
            g,
            {"pattern": "many/*.txt", "max_results": "2", "offset": "1"},
        ),
        c("glob/ties-by-path", g, {"pattern": "ties/*.txt"}),
        c("glob/ign-path", g, {"pattern": "**/*", "directory": "ign"}),
        c("glob/ign-name", g, {"pattern": "*", "match": "name", "directory": "ign"}),
        c("glob/neg-path", g, {"pattern": "**/*", "directory": "neg"}),
        c("glob/neg-name", g, {"pattern": "*", "match": "name", "directory": "neg"}),
        c(
            "glob/gi-a-path",
            g,
            {"pattern": "**/*", "directory": "gi_a", "max_results": 100},
        ),
        c(
            "glob/gi-a-name",
            g,
            {"pattern": "*", "match": "name", "directory": "gi_a", "max_results": 100},
        ),
        c(
            "glob/gi-b-path",
            g,
            {"pattern": "**/*", "directory": "gi_b", "max_results": 100},
        ),
        c(
            "glob/gi-b-name",
            g,
            {"pattern": "*", "match": "name", "directory": "gi_b", "max_results": 100},
        ),
        c(
            "glob/unknown-match-mode-is-path",
            g,
            {"pattern": "*.md", "match": "whatever"},
        ),
        c("glob/absolute-pattern", g, {"pattern": "/etc/*"}),
        c("glob/empty-pattern", g, {"pattern": ""}),
        c("glob/bad-double-star", g, {"pattern": "src/**py"}),
        c("glob/trailing-slash", g, {"pattern": "src/"}),
        c("glob/dot-pattern", g, {"pattern": "."}),
        c("glob/dotdot-pattern", g, {"pattern": "../*"}),
        c("glob/dotdot-inside", g, {"pattern": "src/../README.md"}),
        c("glob/double-slash", g, {"pattern": "src//*.py"}),
        c("glob/dir-missing", g, {"pattern": "*", "directory": "nope"}),
        c(
            "glob/dir-is-file",
            g,
            {"pattern": "*", "directory": "README.md"},
            normalize=True,
        ),
        c(
            "glob/dir-file-component",
            g,
            {"pattern": "*", "directory": "README.md/sub"},
            normalize=True,
        ),
        c(
            "glob/dir-missing-nested",
            g,
            {"pattern": "*", "directory": "src/nope/deeper"},
        ),
        c(
            "glob/dir-outside",
            g,
            {"pattern": "*", "directory": "../outside"},
            normalize=True,
        ),
        c("glob/unterminated-class", g, {"pattern": "[a*.py", "match": "name"}),
        c(
            "glob/upper-case-pattern-windows",
            g,
            {"pattern": "SRC/*.PY"},
            only_os="windows",
        ),
        c(
            "glob/upper-case-name-windows",
            g,
            {"pattern": "*.PY", "match": "name"},
            only_os="windows",
        ),
        c("glob/class-in-directory-part", g, {"pattern": "s[r]c/*.py"}),
        c("glob/star-directory-part", g, {"pattern": "*/helpers.py"}),
        c("glob/star-star-then-name", g, {"pattern": "**/helpers.py"}),
        c("glob/star-star-middle", g, {"pattern": "src/**/helpers.py"}),
        c("glob/question-mark-path", g, {"pattern": "src/?til.py"}),
        c("glob/literal-path", g, {"pattern": "src/util.py"}),
        c("glob/literal-hidden", g, {"pattern": ".env"}),
        c("glob/literal-dir-only", g, {"pattern": "src"}),
        c("glob/dir-with-trailing-slash", g, {"pattern": "*.py", "directory": "src/"}),
        c("glob/windows-separator", g, {"pattern": "src\\util.py"}, only_os="windows"),
        c(
            "glob/name-mode-path-pattern",
            g,
            {"pattern": "src/util.py", "match": "name"},
        ),
        c(
            "glob/name-mode-star-star",
            g,
            {"pattern": "**", "match": "name", "directory": "ties"},
        ),
        c("glob/max-results-one", g, {"pattern": "**/*.py", "max_results": 1}),
    ]

    # ── grep ─────────────────────────────────────────────────────────────
    p = "grep"
    cases += [
        c("grep/todo", p, {"pattern": "TODO"}),
        c(
            "grep/todo-files",
            p,
            {"pattern": "TODO", "output_mode": "files_with_matches"},
        ),
        c("grep/todo-count", p, {"pattern": "TODO", "output_mode": "count"}),
        c("grep/todo-src", p, {"pattern": "TODO", "directory": "src"}),
        c("grep/include-py", p, {"pattern": "TODO", "include": "*.py"}),
        c("grep/include-md", p, {"pattern": "TODO", "include": "*.md"}),
        c("grep/type-py", p, {"pattern": "TODO", "type": "py"}),
        c("grep/type-ts", p, {"pattern": "TODO", "type": "ts"}),
        c("grep/type-upper", p, {"pattern": "TODO", "type": "PY"}),
        c("grep/type-markdown", p, {"pattern": "TODO", "type": "markdown"}),
        c("grep/type-unknown", p, {"pattern": "TODO", "type": "klingon"}),
        c("grep/type-invalid", p, {"pattern": "TODO", "type": "py!"}),
        c("grep/type-padded", p, {"pattern": "TODO", "type": " py "}),
        c("grep/type-too-long", p, {"pattern": "TODO", "type": "a" * 33}),
        c("grep/no-match", p, {"pattern": "zzzzzz"}),
        c(
            "grep/no-match-scope",
            p,
            {"pattern": "zzzzzz", "include": "*.py", "type": "py"},
        ),
        c("grep/no-match-dir", p, {"pattern": "zzzzzz", "directory": "src"}),
        c("grep/regex-alternation", p, {"pattern": "hello|helper"}),
        c("grep/regex-anchors", p, {"pattern": "^def "}),
        c("grep/regex-class", p, {"pattern": "[Aa]lpha"}),
        c("grep/regex-backreference", p, {"pattern": r"(foo)\1"}),
        c("grep/regex-lookahead", p, {"pattern": r"foo(?=\()"}),
        c(
            "grep/regex-invalid",
            p,
            {"pattern": "("},
            prefix_only="Error: Invalid regex: ",
        ),
        c("grep/case-sensitive", p, {"pattern": "needle", "include": "case.txt"}),
        c(
            "grep/case-insensitive",
            p,
            {"pattern": "needle", "include": "case.txt", "case_insensitive": True},
        ),
        c(
            "grep/case-insensitive-string-flag",
            p,
            {"pattern": "needle", "include": "case.txt", "case_insensitive": "yes"},
        ),
        c(
            "grep/fixed-strings",
            p,
            {"pattern": "a.b", "include": "regex.txt", "fixed_strings": True},
        ),
        c("grep/not-fixed", p, {"pattern": "a.b", "include": "regex.txt"}),
        c(
            "grep/fixed-parens",
            p,
            {"pattern": "foo(bar)", "include": "regex.txt", "fixed_strings": True},
        ),
        c(
            "grep/skips-generated-and-hidden",
            p,
            {
                "pattern": "needle",
                "output_mode": "files_with_matches",
                "max_results": 1000,
            },
        ),
        c(
            "grep/needle-count",
            p,
            {"pattern": "needle", "output_mode": "count", "max_results": 1000},
        ),
        c("grep/binary-skipped", p, {"pattern": "needle", "include": "data.bin"}),
        c("grep/long-line", p, {"pattern": "needle", "include": "long_lines.txt"}),
        c("grep/context-1", p, {"pattern": "HIT", "include": "ctx.txt", "context": 1}),
        c("grep/context-2", p, {"pattern": "HIT", "include": "ctx.txt", "context": 2}),
        c(
            "grep/context-big-clamped",
            p,
            {"pattern": "HIT b", "include": "ctx.txt", "context": 99},
        ),
        c(
            "grep/context-negative",
            p,
            {"pattern": "HIT", "include": "ctx.txt", "context": -3},
        ),
        c(
            "grep/context-with-files-mode",
            p,
            {
                "pattern": "HIT",
                "include": "ctx.txt",
                "context": 2,
                "output_mode": "files_with_matches",
            },
        ),
        c(
            "grep/page-first",
            p,
            {"pattern": "match", "include": "lines.txt", "max_results": 5},
        ),
        c(
            "grep/page-second",
            p,
            {"pattern": "match", "include": "lines.txt", "max_results": 5, "offset": 5},
        ),
        c(
            "grep/page-last",
            p,
            {
                "pattern": "match",
                "include": "lines.txt",
                "max_results": 100,
                "offset": 200,
            },
        ),
        c(
            "grep/page-exact",
            p,
            {"pattern": "match", "include": "lines.txt", "max_results": 250},
        ),
        c("grep/page-default-limit", p, {"pattern": "match", "include": "lines.txt"}),
        c(
            "grep/page-limit-clamped",
            p,
            {"pattern": "match", "include": "lines.txt", "max_results": 5000},
        ),
        c(
            "grep/page-limit-zero",
            p,
            {"pattern": "match", "include": "lines.txt", "max_results": 0},
        ),
        c(
            "grep/page-past-end",
            p,
            {"pattern": "match", "include": "lines.txt", "offset": 999},
        ),
        c(
            "grep/page-offset-negative",
            p,
            {
                "pattern": "match",
                "include": "lines.txt",
                "max_results": 2,
                "offset": -5,
            },
        ),
        c(
            "grep/page-with-context",
            p,
            {
                "pattern": "HIT",
                "include": "ctx.txt",
                "context": 1,
                "max_results": 1,
                "offset": 1,
            },
        ),
        c(
            "grep/page-with-context-first",
            p,
            {"pattern": "HIT", "include": "ctx.txt", "context": 1, "max_results": 2},
        ),
        c(
            "grep/files-page-first",
            p,
            {
                "pattern": "needle",
                "output_mode": "files_with_matches",
                "max_results": 3,
            },
        ),
        c(
            "grep/files-page-second",
            p,
            {
                "pattern": "needle",
                "output_mode": "files_with_matches",
                "max_results": 3,
                "offset": 3,
            },
        ),
        c(
            "grep/files-page-past",
            p,
            {"pattern": "needle", "output_mode": "files_with_matches", "offset": 500},
        ),
        c(
            "grep/count-page-first",
            p,
            {"pattern": "needle", "output_mode": "count", "max_results": 3},
        ),
        c(
            "grep/count-page-second",
            p,
            {
                "pattern": "needle",
                "output_mode": "count",
                "max_results": 3,
                "offset": 3,
            },
        ),
        c(
            "grep/count-page-past",
            p,
            {"pattern": "needle", "output_mode": "count", "offset": 500},
        ),
        c(
            "grep/count-lines",
            p,
            {"pattern": "match", "include": "lines.txt", "output_mode": "count"},
        ),
        c(
            "grep/multiline",
            p,
            {"pattern": "alpha\nbeta", "include": "multi.txt", "multiline": True},
        ),
        c(
            "grep/multiline-escaped",
            p,
            {"pattern": r"alpha\r?\nbeta", "include": "multi.txt", "multiline": True},
        ),
        c(
            "grep/multiline-dotall",
            p,
            {"pattern": "beta.*delta", "include": "multi.txt", "multiline": True},
        ),
        c(
            "grep/multiline-count",
            p,
            {
                "pattern": r"a.*\n.*b",
                "include": "multi.txt",
                "multiline": True,
                "output_mode": "count",
            },
        ),
        c(
            "grep/multiline-context",
            p,
            {
                "pattern": r"gamma\ndelta",
                "include": "multi.txt",
                "multiline": True,
                "context": 1,
            },
        ),
        c(
            "grep/newline-without-multiline",
            p,
            {"pattern": r"alpha\nbeta", "include": "multi.txt"},
        ),
        c(
            "grep/newline-literal-without-multiline",
            p,
            {"pattern": "alpha\nbeta", "include": "multi.txt"},
        ),
        c(
            "grep/newline-escaped-backslash-ok",
            p,
            {"pattern": r"alpha\\nbeta", "include": "multi.txt"},
        ),
        c("grep/newline-r", p, {"pattern": r"alpha\rbeta", "include": "multi.txt"}),
        c(
            "grep/fixed-newline",
            p,
            {"pattern": "a\nb", "include": "multi.txt", "fixed_strings": True},
        ),
        c(
            "grep/fixed-backslash-n-ok",
            p,
            {"pattern": r"a\nb", "include": "multi.txt", "fixed_strings": True},
        ),
        c("grep/pattern-too-long", p, {"pattern": "a" * 501}),
        c("grep/pattern-max-length", p, {"pattern": "z" * 500}),
        c("grep/separators", p, {"pattern": "^[bc]", "include": "sep.txt"}),
        c("grep/crlf-file", p, {"pattern": "two", "include": "crlf.txt"}),
        c("grep/cr-only-file", p, {"pattern": "two", "include": "cr_only.txt"}),
        c("grep/bom-file", p, {"pattern": "^bom", "include": "bom.txt"}),
        c("grep/blank-file", p, {"pattern": ".*", "include": "blank.txt"}),
        c(
            "grep/ign",
            p,
            {
                "pattern": "needle",
                "directory": "ign",
                "output_mode": "files_with_matches",
            },
        ),
        c("grep/ign-content", p, {"pattern": "needle", "directory": "ign"}),
        c(
            "grep/neg",
            p,
            {
                "pattern": "needle",
                "directory": "neg",
                "output_mode": "files_with_matches",
            },
        ),
        c(
            "grep/gi-a",
            p,
            {
                "pattern": "x",
                "directory": "gi_a",
                "output_mode": "count",
                "max_results": 100,
            },
        ),
        c(
            "grep/gi-b",
            p,
            {
                "pattern": "x",
                "directory": "gi_b",
                "output_mode": "count",
                "max_results": 100,
            },
        ),
        c("grep/dir-missing", p, {"pattern": "x", "directory": "nope"}),
        c(
            "grep/dir-is-file",
            p,
            {"pattern": "x", "directory": "README.md"},
            normalize=True,
        ),
        c(
            "grep/dir-file-component",
            p,
            {"pattern": "x", "directory": "README.md/sub"},
            normalize=True,
        ),
        c(
            "grep/dir-outside",
            p,
            {"pattern": "x", "directory": "../outside"},
            normalize=True,
        ),
        c("grep/include-empty", p, {"pattern": "TODO", "include": ""}),
        c("grep/include-no-match", p, {"pattern": "TODO", "include": "*.zzz"}),
        c("grep/include-class", p, {"pattern": "TODO", "include": "*.[pm]*"}),
        c("grep/unicode-pattern", p, {"pattern": "café"}),
        c("grep/unicode-class", p, {"pattern": r"\w+ \w+ \w+", "include": "README.md"}),
        c("grep/dot-matches-unicode", p, {"pattern": "caf.", "include": "README.md"}),
        c("grep/spaces-file", p, {"pattern": "spaced"}),
        c(
            "grep/unicode-case-insensitive",
            p,
            {"pattern": "CAFÉ", "include": "README.md", "case_insensitive": True},
        ),
        c(
            "grep/unicode-case-sensitive-miss",
            p,
            {"pattern": "CAFÉ", "include": "README.md"},
        ),
        c("grep/word-boundary", p, {"pattern": r"\bTODO\b", "include": "README.md"}),
        c(
            "grep/digits",
            p,
            {"pattern": r"\d{3}", "include": "lines.txt", "max_results": 3},
        ),
        c(
            "grep/non-greedy",
            p,
            {"pattern": r"l.*?e", "include": "lines.txt", "max_results": 2},
        ),
        c(
            "grep/multiline-anchors",
            p,
            {"pattern": r"^beta$", "include": "multi.txt", "multiline": True},
        ),
        c(
            "grep/multiline-case",
            p,
            {
                "pattern": "ALPHA.beta",
                "include": "multi.txt",
                "multiline": True,
                "case_insensitive": True,
            },
        ),
        c("grep/inline-flag", p, {"pattern": "(?i)needle", "include": "case.txt"}),
        c(
            "grep/python-only-named-group",
            p,
            {"pattern": "(?P<w>needle)", "include": "case.txt"},
        ),
        c(
            "grep/include-case-windows",
            p,
            {"pattern": "TODO", "include": "*.PY"},
            only_os="windows",
        ),
        c("grep/empty-pattern", p, {"pattern": "", "include": "nonl.txt"}),
        c(
            "grep/dot-star-all-lines",
            p,
            {"pattern": ".*", "include": "nonl.txt", "output_mode": "count"},
        ),
        c(
            "grep/caret-only",
            p,
            {"pattern": "^", "include": "ctx.txt", "output_mode": "count"},
        ),
        c(
            "grep/trailing-context-at-eof",
            p,
            {"pattern": "nine", "include": "ctx.txt", "context": 3},
        ),
        c(
            "grep/leading-context-at-bof",
            p,
            {"pattern": "one", "include": "ctx.txt", "context": 3},
        ),
    ]

    # ── confinement (read / ls / glob / grep) ────────────────────────────
    cases += [
        c(
            "confine/read-dotdot",
            "read",
            {"path": "../outside/secret.txt"},
            normalize=True,
        ),
        c(
            "confine/read-dotdot-deep",
            "read",
            {"path": "src/../../outside/secret.txt"},
            normalize=True,
        ),
        c("confine/read-dotdot-reenter", "read", {"path": "../ws/README.md"}),
        c("confine/read-dotdot-only", "read", {"path": ".."}, normalize=True),
        c(
            "confine/read-absolute",
            "read",
            {"path": "<OUT>/secret.txt"},
            normalize=True,
        ),
        c("confine/read-tilde", "read", {"path": "~/secret.txt"}),
        c("confine/read-tilde-bare", "read", {"path": "~"}),
        c("confine/read-tilde-user", "read", {"path": "~root/.ssh/id_rsa"}),
        c("confine/read-tilde-middle-ok", "read", {"path": "a~b"}),
        # Python's `lstat` words the NUL error per OS; the Windows text is recorded.
        c("confine/read-nul", "read", {"path": "a\u0000b"}, only_os="windows"),
        c(
            "confine/read-nul-after-dir",
            "read",
            {"path": "a/\u0000"},
            only_os="windows",
        ),
        c("confine/ls-nul", "ls", {"path": "a\u0000b"}, only_os="windows"),
        c(
            "confine/glob-nul-root",
            "glob",
            {"pattern": "*", "directory": "a\u0000b"},
            only_os="windows",
        ),
        c(
            "confine/grep-nul-root",
            "grep",
            {"pattern": "x", "directory": "a\u0000b"},
            only_os="windows",
        ),
        c("confine/glob-nul-pattern", "glob", {"pattern": "a\u0000b"}),
        c(
            "confine/glob-nul-pattern-name",
            "glob",
            {"pattern": "a\u0000b", "match": "name"},
        ),
        c("confine/grep-nul-pattern", "grep", {"pattern": "a\u0000b"}),
        c("confine/grep-nul-include", "grep", {"pattern": "x", "include": "a\u0000b"}),
        c(
            "confine/read-drive-letter",
            "read",
            {"path": "C:\\Windows\\win.ini"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/read-drive-letter-slash",
            "read",
            {"path": "C:/Windows/win.ini"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/read-drive-other",
            "read",
            {"path": "Z:\\nope\\x.txt"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/read-unc",
            "read",
            {"path": "\\\\evil-host\\share\\x.txt"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/read-unc-slash",
            "read",
            {"path": "//evil-host/share/x.txt"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/read-unc-dotdot",
            "read",
            {"path": "\\\\evil-host\\share\\a\\..\\x.txt"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/read-rooted-no-drive",
            "read",
            {"path": "\\Windows\\win.ini"},
            only_os="windows",
            normalize=True,
            normalize_drive=True,
        ),
        c(
            "confine/read-verbatim-drive",
            "read",
            {"path": "\\\\?\\C:\\Windows\\win.ini"},
            only_os="windows",
            normalize=True,
        ),
        c("confine/ls-dotdot", "ls", {"path": ".."}, normalize=True),
        c("confine/ls-dotdot-outside", "ls", {"path": "../outside"}, normalize=True),
        c("confine/ls-absolute", "ls", {"path": "<OUT>"}, normalize=True),
        c("confine/ls-tilde", "ls", {"path": "~"}),
        c(
            "confine/ls-drive-letter",
            "ls",
            {"path": "C:\\"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/ls-unc",
            "ls",
            {"path": "\\\\evil-host\\share"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/glob-dotdot-root",
            "glob",
            {"pattern": "*", "directory": ".."},
            normalize=True,
        ),
        c(
            "confine/glob-absolute-root",
            "glob",
            {"pattern": "*", "directory": "<OUT>"},
            normalize=True,
        ),
        c("confine/glob-tilde-root", "glob", {"pattern": "*", "directory": "~"}),
        c(
            "confine/glob-unc-root",
            "glob",
            {"pattern": "*", "directory": "\\\\evil-host\\share"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/grep-dotdot-root",
            "grep",
            {"pattern": "SECRET", "directory": ".."},
            normalize=True,
        ),
        c(
            "confine/grep-absolute-root",
            "grep",
            {"pattern": "SECRET", "directory": "<OUT>"},
            normalize=True,
        ),
        c("confine/grep-tilde-root", "grep", {"pattern": "SECRET", "directory": "~"}),
        c(
            "confine/grep-drive-root",
            "grep",
            {"pattern": "x", "directory": "C:\\Windows"},
            only_os="windows",
            normalize=True,
        ),
        c(
            "confine/grep-unc-root",
            "grep",
            {"pattern": "x", "directory": "\\\\evil-host\\share"},
            only_os="windows",
            normalize=True,
        ),
        # The "links" fixture has `escape` -> outside dir and `alias` -> src,
        # created by the runner; these cases are skipped where links cannot be made.
        c(
            "confine/link-read-through-dir",
            "read",
            {"path": "escape/secret.txt"},
            fixture="links",
            normalize=True,
        ),
        c("confine/link-ls", "ls", {"path": "escape"}, fixture="links", normalize=True),
        c(
            "confine/link-glob-root",
            "glob",
            {"pattern": "*", "directory": "escape"},
            fixture="links",
            normalize=True,
        ),
        c(
            "confine/link-grep-root",
            "grep",
            {"pattern": "SECRET", "directory": "escape"},
            fixture="links",
            normalize=True,
        ),
        c(
            "confine/link-inside-read",
            "read",
            {"path": "alias/main.py"},
            fixture="links",
        ),
        c("confine/link-inside-ls", "ls", {"path": "alias"}, fixture="links"),
    ]

    # ── argument validation ──────────────────────────────────────────────
    cases += [
        c("args/read-missing-path", "read", {}),
        c("args/read-path-int", "read", {"path": 1}),
        c("args/read-path-null", "read", {"path": None}),
        c("args/read-path-list", "read", {"path": ["a"]}),
        c("args/read-offset-text", "read", {"path": "README.md", "offset": "abc"}),
        c("args/read-offset-fraction", "read", {"path": "README.md", "offset": 2.5}),
        c("args/read-offset-null", "read", {"path": "README.md", "offset": None}),
        c("args/read-offset-list", "read", {"path": "README.md", "offset": [1]}),
        c("args/read-limit-text", "read", {"path": "README.md", "limit": "abc"}),
        c(
            "args/read-limit-fraction-text",
            "read",
            {"path": "README.md", "limit": "1.5"},
        ),
        c(
            "args/read-extra-args-ignored",
            "read",
            {"path": "README.md", "limit": 1, "bogus": 1},
        ),
        c("args/read-two-errors", "read", {"offset": "x"}),
        c("args/read-dict-input", "read", {"path": {"a": [1, None, True, "x'y"]}}),
        c("args/read-long-input", "read", {"path": list(range(40))}),
        c(
            "args/read-offset-underscore",
            "read",
            {"path": "README.md", "offset": "1_000", "limit": 1},
        ),
        c(
            "args/read-offset-plus",
            "read",
            {"path": "README.md", "offset": "+2", "limit": 1},
        ),
        c(
            "args/read-offset-minus",
            "read",
            {"path": "README.md", "offset": "-2", "limit": 1},
        ),
        c(
            "args/read-offset-decimal-zero",
            "read",
            {"path": "README.md", "offset": "3.0", "limit": 1},
        ),
        c(
            "args/read-offset-trailing-dot",
            "read",
            {"path": "README.md", "offset": "5."},
        ),
        c("args/read-offset-exponent", "read", {"path": "README.md", "offset": "1e3"}),
        c(
            "args/read-offset-spaces",
            "read",
            {"path": "README.md", "offset": " 4 ", "limit": 1},
        ),
        c("args/read-offset-empty", "read", {"path": "README.md", "offset": ""}),
        c("args/read-offset-hex", "read", {"path": "README.md", "offset": "0x10"}),
        c("args/ls-path-int", "ls", {"path": 5}),
        c("args/glob-missing-pattern", "glob", {}),
        c("args/glob-missing-pattern-with-extra", "glob", {"directory": "src"}),
        c(
            "args/glob-max-results-text",
            "glob",
            {"pattern": "*", "max_results": "many"},
        ),
        c(
            "args/glob-offset-bool",
            "glob",
            {"pattern": "many/*.txt", "offset": True, "max_results": 1},
        ),
        c("args/grep-missing-pattern", "grep", {}),
        c("args/grep-bad-mode", "grep", {"pattern": "a", "output_mode": "everything"}),
        c("args/grep-bad-mode-type", "grep", {"pattern": "a", "output_mode": 3}),
        c("args/grep-bool-text", "grep", {"pattern": "a", "case_insensitive": "maybe"}),
        c("args/grep-bool-int", "grep", {"pattern": "a", "multiline": 2}),
        c(
            "args/grep-bool-one",
            "grep",
            {"pattern": "needle", "include": "case.txt", "case_insensitive": 1},
        ),
        c("args/grep-bool-null", "grep", {"pattern": "a", "fixed_strings": None}),
        c("args/grep-context-text", "grep", {"pattern": "a", "context": "lots"}),
        c(
            "args/grep-many-errors",
            "grep",
            {"output_mode": "x", "context": "y", "multiline": "z"},
        ),
    ]
    return cases


def build() -> dict[str, Any]:
    files = _files()
    # Every file gets a deterministic mtime unless it set one.
    for index, name in enumerate(sorted(files)):
        files[name].setdefault("mtime", MTIME_BASE + index * 60)
    link_files = {
        "src/main.py": _text("print('linked')\n", MTIME_BASE),
        "src/util.py": _text("x = 1\n", MTIME_BASE + 60),
    }
    return {
        "fixtures": {
            "main": {"files": files, "dirs": ["empty_dir"], "links": []},
            "links": {
                "files": link_files,
                "dirs": [],
                "links": [
                    {"path": "escape", "target": "<OUT>"},
                    {"path": "alias", "target": "<WS>/src"},
                ],
            },
        },
        "outside": {"secret.txt": "TOP SECRET\n"},
        "cases": _cases(),
    }


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    target = (
        Path(__file__).resolve().parents[2]
        / "server/crates/area-tools/tests/parity/cases.json"
    )
    target.write_text(
        json.dumps(build(), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {target}", file=sys.stderr)
