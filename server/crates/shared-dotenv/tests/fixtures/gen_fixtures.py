"""Record Python itself, never a reimplementation. Run from the repository root.

uv run python server/crates/shared-dotenv/tests/fixtures/gen_fixtures.py
Text writes are recorded for both newline conventions through real TextIOWrapper
streams; the writer logic and resulting bytes are otherwise untouched.
"""

from __future__ import annotations

import builtins
import importlib.metadata
import io
import json
import logging
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from dotenv import dotenv_values

assert importlib.metadata.version("python-dotenv") == "1.2.2"
logging.getLogger("dotenv.main").disabled = True
DEST = Path(__file__).parent
FAKE_ENV = {"A": "environment", "EXT": "external", "EMPTY": "", "HOME": "/fake"}
TEXTS = [
    "",
    "# comment\n",
    "A=one\nB=two\n",
    "A\nB=\n",
    "A=  \n",
    " export A = one \n",
    "export\tA=one\n",
    "exportA=one\n",
    "export\nA=x",
    "A=hello # comment\n",
    "A=hello#literal\n",
    "A=hello\t#comment\n",
    "A=#literal\n",
    "A='hello # literal' # comment\n",
    'A="hello # literal"\n',
    r"A='a\nb\\c\'d'" + "\n",
    r'''A="a\\b\"c\nd\re\tf\ag\bh\fi\vj\'k"''' + "\n",
    r'A="\q\u1234\x41\0\$"' + "\n",
    "A='first\nsecond'\nB=end\n",
    'A="first\nsecond"\nB=end\n',
    "'quoted key'=one\n",
    "''=bad\nB=ok",
    "A=one\nA=two\nB=x\nA=three",
    "A=one\nA\nB=${A:-default}",
    "A=${EXT}\nB=${UNDEFINED}\n",
    "A=${UNDEFINED:-default}\n",
    "A=${EMPTY:-default}\nB=${MISSING:-}\n",
    "A=\nB=${A:-default}\n",
    "A\nB=${A:-default}\n",
    "A=local\nB=${A}\n",
    "B=${A}\nA=local\nC=${A}",
    "A=${A:-default}\nB=${A}\n",
    "A='${EXT}'\n",
    'A="${EXT}"\n',
    "A=$EXT\nB=${EXT-default}\nC=${EXT:bad}\nD=${}\n",
    "A=${MISSING:-${EXT}}\n",
    "A=${MISSING:-a:b}\n",
    "A=${bad:name}\n",
    "A=one\r\nB=two\rC='x\r\ny'\n",
    "\ufeffA=one\nB=${A}\n",
    "bad line = nope\nA=ok\n",
    "A='unclosed\nB=ok\n",
    'A="unclosed\nB=ok\n',
    "A='ok'garbage\nB=ok\n",
    'A="ok" tail\nB=ok\n',
    "=bad\nA=ok\n",
    " # comment\n\n\tA=x\n",
    "A=one\v #hi\nB=x\n",
    "A=雪☃\nB=${A}\n",
    "'multi\nkey'=yes\n",
    "A='a\\\\'\nB=ok\n",
    "#a=b\nA=a=b=c\n",
    "A=one\nB=${A}${EXT}${MISSING:-d}\n",
    "A=one\nA=${A}two\n",
    "A=${{X}\nB=${MISSING:-a${EXT}}\n",
    "A\x1c=\x1dyes\x1f\n",
    "A=one\u0085#comment\n",
    "A='x\rnext'\rB=last\r",
    'A="a\\\\\\"b"\n',
    "'a=b# c'=x\n",
    "A =x\nA # bare\nB=${A:-d}\n",
    r"""A='\"\a\b\f\n\r\t\v\q' """ + "\n",
    "A='ok'\n# middle comment\nB=next\n",
    "A='first\nsecond'junk\nB=keep\n",
    "A='x\\'\nB=keep\n",
    'A="x\\"\nB=keep\n',
    "A=${MISSING:-oops\nB=${EXT}\n",
    "A=${BAD:wrong${EXT}}\n",
    "A='a'b'\nB=keep\n",
    'A="a"b"\nB=keep\n',
]


def readers():
    cases = []
    for number, text in enumerate(TEXTS):
        for env in ({}, FAKE_ENV):
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, env, clear=True),
            ):
                path = Path(directory) / ".env"
                path.write_bytes(text.encode())
                expected = list(dotenv_values(path).items())
            cases.append(
                {
                    "name": f"text-{number}-env-{bool(env)}",
                    "text": text,
                    "env": env,
                    "expected": expected,
                }
            )
    return cases


WRITES = [
    (None, []),
    (None, [("A", "one")]),
    (None, [("A", "")]),
    ("", []),
    ("", [("A", "one"), ("B", "two")]),
    ("A=old\n", [("A", "new")]),
    ("A=old\n", [("A", "")]),
    ("A=old\nA=second\n", [("A", "new")]),
    ("A=old\nA=second\n", [("A", "")]),
    (" A = old\nB=keep", [("A", "new"), ("C", "third")]),
    ("# comment\n\nUNKNOWN=x\n", [("A", "one")]),
    ("A\n", [("A", "new")]),
    ("A\n", [("A", "")]),
    ("#A=old\n  # A=old\nA=old", [("A", "new")]),
    ("export A=old\n", [("A", "new")]),
    ("A=old\r\nB=keep\r", [("A", "new")]),
    ("\ufeffA=old\n", [("A", "new")]),
    (None, [("A", 'a"b\\c'), ("B", "雪☃")]),
    ("A=old\n", [("A", " leading and trailing ")]),
    ("A=old\n", [("A", "# hash and = equals")]),
    ("A=old\n\n", []),
    ("\n", [("_A9", "val")]),
    (
        "A=old\vB=keep\fC=keep\x1cD=keep\x1dE=keep\x1eF=keep\x85G=keep\u2028H=keep\u2029",
        [("A", "new")],
    ),
    (None, [("APP_ENV", "custom"), ("B", "")]),
    ("A=old\n# annotation\n", [("A", "new"), ("B", "two")]),
]


def writers():
    # Import only after fencing app config/state away from the user's files.
    with (
        tempfile.TemporaryDirectory() as app_dir,
        patch.dict(
            os.environ,
            {
                "EVOFLUX_CONFIG_DIR": app_dir,
                "EVOFLUX_DATA_DIR": app_dir,
                "EVOFLUX_STATE_DIR": app_dir,
                "EVOFLUX_CACHE_DIR": app_dir,
            },
        ),
    ):
        from app.cli.seed import write_env_credentials
        from app.api.routes import mcp

        cases = []
        comments = {"A": "# A annotation", "B": "# B annotation"}
        original_open = io.open
        for number, (existing, updates) in enumerate(WRITES):
            for mode in ("credentials", "mcp"):
                outputs = {}
                created = existing is None and (bool(updates) or mode == "credentials")
                for label, newline in (("unix", "\n"), ("windows", "\r\n")):

                    def text_open(
                        file,
                        mode="r",
                        buffering=-1,
                        encoding=None,
                        errors=None,
                        newline_arg=None,
                        closefd=True,
                        opener=None,
                        **kwargs,
                    ):
                        chosen = kwargs.pop("newline", newline_arg)
                        if (
                            "b" not in mode
                            and any(flag in mode for flag in "wax")
                            and chosen is None
                        ):
                            chosen = newline
                        return original_open(
                            file,
                            mode,
                            buffering,
                            encoding,
                            errors,
                            chosen,
                            closefd,
                            opener,
                        )

                    with (
                        tempfile.TemporaryDirectory() as directory,
                        patch.dict(os.environ, {}, clear=True),
                    ):
                        path = Path(directory) / ".env"
                        if existing is not None:
                            path.write_bytes(existing.encode())
                        with (
                            patch("io.open", text_open),
                            patch.object(builtins, "open", text_open),
                        ):
                            if mode == "credentials":
                                assert write_env_credentials(
                                    path, dict(updates), comments=comments
                                ) == (existing is None)
                            else:
                                with patch.object(
                                    mcp.settings, "EVOFLUX_CONFIG_DIR", Path(directory)
                                ):
                                    mcp._save_env_values(dict(updates))
                        outputs[label] = (
                            list(path.read_bytes()) if path.exists() else None
                        )
                cases.append(
                    {
                        "name": f"write-{number}-{mode}",
                        "mode": mode,
                        "existing": existing,
                        "updates": updates,
                        "comments": list(comments.items()),
                        "created": created,
                        "expected": outputs,
                    }
                )
        return cases


if __name__ == "__main__":
    for name, cases in (("read", readers()), ("write", writers())):
        (DEST / f"{name}.json").write_text(
            json.dumps(cases, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"{name}: {len(cases)} cases")
