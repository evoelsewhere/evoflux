"""Generate the PyYAML differential fixtures for evoflux-shared-yaml.

Run from the repository root: ``uv run python server/crates/shared-yaml/tests/fixtures/gen_fixtures.py``.
The expected values come from PyYAML ``safe_load`` / ``safe_dump``; values are
written as tagged JSON so dates, non-string keys and floats survive.
"""

import datetime
import json
import math
import pathlib

import yaml

HERE = pathlib.Path(__file__).parent

LOAD_CASES = [
    # Booleans and nulls, YAML 1.1.
    "a: yes\nb: No\nc: ON\nd: off\ne: true\nf: FALSE\ng: y\nh: n\n",
    "a: null\nb: ~\nc:\nd: Null\ne: NULL\nf: nil\n",
    "name: on\n",
    "- yes\n- 'yes'\n- \"off\"\n- !!str on\n",
    # Integers.
    "a: 0\nb: -0\nc: +7\nd: 1_000\ne: 017\nf: 0o17\ng: 08\nh: 0x1F\ni: 0b101\nj: 190:20:30\nk: -1:30\n",
    "a: 12345678901234567890\nb: 007\nc: 0_7\nd: 0x_ff\n",
    # Floats.
    "a: 1.0\nb: .5\nc: 1.\nd: 1e3\ne: 1.0e+3\nf: 1.0e3\ng: -.inf\nh: .NaN\ni: 190:20:30.15\nj: 6.8523015e+5\nk: 1_0.5\n",
    "a: 3.14159265358979\nb: 0.1\nc: 1.5e-10\nd: +.Inf\ne: 100.\n",
    # Timestamps.
    "a: 2001-12-14\nb: 2001-12-14t21:59:43.10-05:00\nc: 2001-12-14 21:59:43.10 -5\nd: 2001-12-15T02:59:43.1Z\ne: 2001-12-15 2:59:43.10\n",
    "a: 2002-1-1\nb: 2002-1-1 1:02:03\nc: 2024-02-29\nd: 2001-12-14 21:59:43.1234567\n",
    "created: 2024-01-01\nupdated: 2024-01-01 10:00:00+01:00\n",
    # Strings and quoting.
    "a: 'single ''quoted'''\nb: \"double \\\"quoted\\\" \\t tab \\u00e9\"\nc: plain text here\nd: 'a: b'\n",
    "a: '1.0'\nb: \"123\"\nc: ''\nd: \"\"\ne: ' '\n",
    "s: café\nt: \"\\xE9\"\nu: 日本語\n",
    "k: x # comment\n# whole line\nl: 'y # not comment'\n",
    # Block scalars.
    "lit: |\n  line one\n  line two\nfold: >\n  folded\n  text\n\n  para\n",
    "keep: |+\n  a\n\nstrip: |-\n  b\nclip: |\n  c\n\n",
    "ind: |2\n    indented\n  less\n",
    # Multi-line plain and quoted.
    "a: this is\n  a multi line\n  plain scalar\nb: 'quoted\n  across lines'\n",
    "a: \"double\\\n  continued\"\n",
    # Collections.
    "tools: [read, write, 'bash']\nmeta: {a: 1, b: [x, y]}\n",
    "- - a\n  - b\n- - c\n- {}\n- []\n",
    "outer:\n  inner:\n    deep: 1\n  list:\n  - 1\n  - two: 2\n    three: 3\n",
    "a:\n- 1\n- 2\nb:\n  - 3\n",
    "[1, 2, [3, [4, 5]]]\n",
    "{a: 1}\n",
    "- a\n- b\n",
    # Keys of every kind.
    "1: one\n2.5: two\ntrue: three\nnull: four\n2024-01-01: five\n",
    "1: a\ntrue: b\n1.0: c\n",
    "a: 1\na: 2\nb: 3\n",
    "? complex key\n: value\n",
    "'quoted key': 1\n\"dq key\": 2\n",
    "yes: 1\nno: 2\non: 3\n",
    # Anchors, aliases and merge keys.
    "base: &b {x: 1, y: 2}\nderived:\n  <<: *b\n  y: 3\n",
    "a: &a {k: 1}\nb: &b {k: 2, m: 2}\nc:\n  <<: [*a, *b]\n  n: 3\n",
    "a: &x hello\nb: *x\nc: [*x, *x]\n",
    "m: &m\n  <<: {inner: 1}\n  own: 2\nn:\n  <<: *m\n",
    "'<<': not a merge\n",
    "=: value key\n",
    "list: &l [1, 2]\ncopy: *l\n",
    # Explicit tags.
    "a: !!str 123\nb: !!int '42'\nc: !!float '1'\nd: !!bool 'yes'\ne: !!null ''\n",
    "a: ! 123\nb: ! 'yes'\nc: !!seq [1]\nd: !!map {a: 1}\n",
    "a: !!int 0o17\nb: !!float +-1\nc: !!timestamp 2020-01-02\n",
    # Documents.
    "",
    "# only a comment\n",
    "---\n",
    "--- 42\n",
    "---\na: 1\n...\n",
    "plain root scalar\n",
    "'quoted root'\n",
    "%YAML 1.1\n---\na: 1\n",
    # Front matter shapes.
    "name: reviewer\ndescription: Reviews code — carefully.\ntools:\n  - read\n  - grep\nmodel: anthropic:claude\n",
    "name: off\ndescription: a skill\n",
    "name: test\nversion: 1.0\nenabled: yes\ncount: 007\n",
    # Settings-shaped documents.
    "sandbox:\n  allow: []\ncontext:\n  summary_trigger_tokens: 60.0\nteam_spawn:\n  enabled: true\n",
    "response_style:\n  tone: 'off'\n  verbosity: null\n",
    # Whitespace and unicode edge cases.
    "a:    spaced   value   \nb:\ttab\n",
    "emoji: \"\\U0001F600\"\nnel: \"\\N\"\nnbsp: \"\\_\"\n",
    "long: " + "word " * 30 + "end\n",
    # Errors.
    "a: [1, 2\n",
    "a: b: c\n",
    "- a\nb: c\n",
    "a: *undefined\n",
    "? [a]\n: b\n",
    "? {a: 1}\n: b\n",
    "a: !!int abc\n",
    "a: !!bool maybe\n",
    "a: !custom x\n",
    "a: =\n",
    "a:\n  <<: 1\n",
    "a:\n  <<: [1]\n",
    "a: !!timestamp nope\n",
    "a: !!str [1]\n",
    "a: !!seq x\n",
    "--- 1\n--- 2\n",
    "a: \"unterminated\n",
    "\ta: 1\n",
    "a:\tb\n",
    "a: 1\t\n",
    "- \ta\n",
    "[\t1]\n",
    # Tabs PyYAML accepts: quoted, block bodies, comments.
    "a: 'x\ty'\nb: \"\tz\"\nc: |\n  \tlit\n  x\ty\nd: 1 # c\tc\n# \tfull\n",
    "a: '#x\t'\nb: >\n  f\t#\n",
    "a: 2001-02-30\n",
]

DUMP_CASES = [
    {"a": 1, "b": 2},
    {"z": 1, "a": 2, "m": 3},
    {"off": "off", "yes": "yes", "no": "No", "on": "ON", "y": "y", "n": "n"},
    {"null": None, "empty": "", "space": " ", "tilde": "~", "nullstr": "null"},
    {"i": 7, "neg": -3, "big": 12345678901234567890, "zero": 0, "octal": "017", "hex": "0x1F", "sx": "1:30"},
    {"f": 1.0, "g": 0.1, "h": 60.0, "i": 1e16, "j": 1e-5, "k": -2.5, "l": float("inf"), "m": float("-inf"), "n": float("nan")},
    {"fs": "1.0", "fe": "1e3", "fe2": "1.0e+3", "ints": "123", "neg": "-1", "dot": ".5", "inf": ".inf"},
    {"t": True, "f": False, "ts": "true", "fs": "False"},
    {"d": datetime.date(2024, 1, 1), "dt": datetime.datetime(2024, 1, 1, 10, 0, 0)},
    {"dtz": datetime.datetime(2024, 1, 1, 10, 0, 0, 500, tzinfo=datetime.timezone(datetime.timedelta(hours=-5, minutes=-30)))},
    {"utc": datetime.datetime(2001, 12, 15, 2, 59, 43, 100000, tzinfo=datetime.timezone.utc)},
    {"ds": "2024-01-01", "dts": "2024-01-01 10:00:00"},
    {"colon": "a: b", "hash": "a #b", "hash2": "a#b", "lead": "- x", "q": "?", "qs": "? x", "col": ":x", "dash": "-", "dashx": "-x"},
    {"ind": "[x]", "brace": "{x}", "amp": "&a", "star": "*a", "bang": "!x", "pipe": "|", "gt": ">", "pct": "%x", "at": "@x", "tick": "`x"},
    {"comma": "a, b", "flowind": "a[b]", "sq": "'q'", "dq": '"q"', "both": "it's \"x\""},
    {"doc": "--- x", "dots": "... y", "trail": "x ", "lead": " x"},
    {"ml": "line one\nline two", "mlt": "trailing\n", "mlb": "\nleading", "blank": "a\n\nb", "spacebreak": "a \nb", "breakspace": "a\n b"},
    {"cafe": "café", "jp": "日本語", "dash": "Reviews code — carefully.", "emoji": "😀"},
    {"tab": "a\tb", "cr": "a\rb", "nul": "a\x00b", "bell": "\x07", "esc": "\x1b", "nel": "\x85", "nbsp": "\xa0", "ls": "\u2028", "bom": "\ufeff", "del": "\x7f"},
    {"bs": "back\\slash", "dqin": 'say "hi"', "c1": "\x9f"},
    {"long": "word " * 30 + "end"},
    {"longnosp": "x" * 100},
    {"longsq": "it's " * 25 + "done"},
    {"longdq": "é " * 50 + "end"},
    {"longdq2": "é" * 100},
    {"longdqsp": "a" * 75 + "  é  " + "b" * 20},
    {"longml": ("word " * 20 + "\n") * 3},
    {"k" * 130: "long key"},
    {"multiline\nkey": 1},
    {"": "empty key", " ": "space key"},
    {1: "int", 2.5: "float", True: "bool", None: "none", datetime.date(2024, 1, 1): "date"},
    {"list": [1, "two", 3.0, None, True]},
    {"nested": {"a": {"b": {"c": [1, {"d": 2, "e": [3, 4]}]}}}},
    {"empties": {"m": {}, "l": [], "lm": [{}], "ll": [[]]}},
    {"seqseq": [[1, 2], [3, [4, 5]], []]},
    {"seqmap": [{"a": 1, "b": 2}, {"c": {"d": 3}}, {"e": [1, 2]}]},
    [1, 2, 3],
    [{"a": 1}, [1, 2], "x"],
    [],
    {},
    "root string",
    "off",
    "",
    42,
    1.5,
    None,
    True,
    datetime.date(2020, 2, 2),
    "multi\nline root",
    {"tools": ["read", "write"], "name": "x", "model": "anthropic:claude-x", "description": "A " * 50},
    {"sandbox": {"allow": [], "deny": ["*.env"], "mode": "workspace-write"}, "context": {"summary_trigger_tokens": 60.0, "keep": 3}},
    {"name": "agent", "version": 1.0, "enabled": True, "count": 7, "created": datetime.date(2024, 1, 1)},
    {"url": "https://example.com/path?q=1#frag", "path": "C:\\Users\\x", "email": "a@b.c", "glob": "**/*.py"},
    {"ver": "1.2.3", "semver": "v1.2", "port": "8080", "ip": "127.0.0.1", "time": "10:30", "neg": "-0"},
    {"keys with spaces": 1, "key:colon": 2, "key#hash": 3, "-dash": 4},
    {"weird": "a  b   c", "endcolon": "x:", "midcolon": "a:b", "q2": "a?b"},
    {"nested_long": {"inner": {"deeper": "word " * 25 + "end"}}},
    {"seq_long": ["word " * 25 + "end", "x"]},
    {"surrogate_free": "\U0010fffd", "maxbmp": "\ufffd", "private": "\ue000"},
    {"bools_in_list": ["yes", "no", "on", "off", "true"]},
    {"leading_zero": "0123", "plus": "+1", "under": "1_000", "dotonly": ".", "e": "e", "dash_num": "-1.5"},
    {"equals": "=", "merge": "<<", "tildes": "~~"},
]


def tagged(value):
    if value is None:
        return {"t": "null"}
    if value is True or value is False:
        return {"t": "bool", "v": value}
    if isinstance(value, int):
        return {"t": "int", "v": str(value)}
    if isinstance(value, float):
        if math.isnan(value):
            return {"t": "float", "v": "nan"}
        return {"t": "float", "v": repr(value)}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, datetime.datetime):
        return {"t": "timestamp", "v": value.isoformat(" ")}
    if isinstance(value, datetime.date):
        return {"t": "timestamp", "v": value.isoformat()}
    if isinstance(value, list):
        return {"t": "seq", "v": [tagged(v) for v in value]}
    if isinstance(value, dict):
        return {"t": "map", "v": [[tagged(k), tagged(v)] for k, v in value.items()]}
    raise TypeError(type(value))


def load_case(text):
    try:
        return {"yaml": text, "value": tagged(yaml.safe_load(text))}
    except Exception as exc:  # noqa: BLE001 - every error is one expected outcome
        return {"yaml": text, "error": type(exc).__name__}


def dump_case(value):
    out = {"value": tagged(value)}
    for sort_keys in (False, True):
        for allow_unicode in (False, True):
            name = f"sort={int(sort_keys)},unicode={int(allow_unicode)}"
            try:
                out[name] = yaml.safe_dump(value, sort_keys=sort_keys, allow_unicode=allow_unicode)
            except TypeError:
                out[name] = None
    return out


def real_documents():
    """What EvoFlux writes: the default ``settings.yaml`` and the contract snapshots."""
    from app.core.runtime_settings import RuntimeSettings

    yield RuntimeSettings().model_dump(mode="json", exclude_none=True)
    root = HERE.parents[4] / "contract-tests"
    for snapshot in (
        "settings-providers/snapshots/settings_yaml_full_dump.json",
        "imports/snapshots/auto_sync_saved_settings.json",
    ):
        yield json.loads((root / snapshot).read_text(encoding="utf-8"))


def main():
    DUMP_CASES.extend(real_documents())
    (HERE / "load_cases.json").write_text(
        json.dumps([load_case(c) for c in LOAD_CASES], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (HERE / "dump_cases.json").write_text(
        json.dumps([dump_case(c) for c in DUMP_CASES], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"yaml {yaml.__version__}: {len(LOAD_CASES)} load cases, {len(DUMP_CASES)} dump cases")


if __name__ == "__main__":
    main()
