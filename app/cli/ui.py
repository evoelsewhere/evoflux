"""Terminal UI helpers: ANSI colour codes, banner, and interactive prompts.

All output is plain text when stdout is not a TTY so CI logs stay readable.
"""

from __future__ import annotations

import sys

from app.core.version import VERSION

_IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text


def _dim(t: str) -> str:
    return _c("2", t)


def _bold(t: str) -> str:
    return _c("1", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _green(t: str) -> str:
    return _c("32", t)


def _red(t: str) -> str:
    return _c("31", t)


def _yellow(t: str) -> str:
    return _c("33", t)


# ASCII wordmark. Pre-rendered with `pyfiglet` (font: ``rectangles``) and
# baked in so we don't take a runtime dep for a banner. Kept narrow
# (~53 cols) to fit a 60-char terminal cleanly. Drawn with U+005F / U+007C
# / U+0027 so it lands as plain ASCII in non-UTF8 environments.
_WORDMARK = (
    " _____         _____ _         \n"
    "|   __|_ _ ___|   __| |_ _ _ _ \n"
    "|   __| | | . |   __| | | |_'_|\n"
    "|_____|\_/|___|__|  |_|___|_,_|"
)


def _print_banner(*, host: str, port: int) -> None:
    """Print the startup banner.

    Two layouts depending on TTY:

    - **TTY**: ASCII wordmark + version + URL. The URL is the only
      thing the user clicks, so it gets the only line of weight.
    - **non-TTY** (piped, CI, log files): plain text — drop the wordmark
      and the colours so log scrapers stay clean.
    """
    url = f"http://{host}:{port}"

    print()
    if _IS_TTY:
        for line in _WORDMARK.splitlines():
            print(f"  {_cyan(line)}")
        print()
        print(f"  {_dim(f'v{VERSION}')}")
        print(f"  {_dim('Open:')}  {_bold(url)}")
    else:
        print(f"  EvoFlux v{VERSION}")
        print(f"  Open: {url}")
    print()


def _ask(prompt: str) -> str:
    """Print a prompt and read a stripped line from stdin."""
    print(f"  {_cyan('?')} {prompt} ", end="", flush=True)
    return input().strip()


def _menu(prompt: str, options: list[str]) -> int:
    """Display a numbered menu, return 0-based index of chosen item."""
    print(f"  {_cyan('?')} {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"    {_dim(str(i) + ')')} {opt}")
    while True:
        raw = _ask(f"Enter number [1-{len(options)}]:")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  {_yellow('⚠')}  Please enter a number between 1 and {len(options)}.")
