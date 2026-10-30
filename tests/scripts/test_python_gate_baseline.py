import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "migration"
    / "python_gate_baseline.sh"
)
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required")


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "migration").mkdir(parents=True)
    (repo / "app").mkdir()
    (repo / "tests").mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "migration" / SCRIPT.name)
    (repo / "app" / "old.py").write_text(
        "import os\n", encoding="utf-8"
    )  # F401, pre-existing
    (repo / "tests" / "test_a.py").write_text(
        "def test_a():\n    assert True\n", encoding="utf-8"
    )
    git(repo.parent, "init", "-b", "base", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")
    git(repo, "update-ref", "refs/remotes/origin/base", "HEAD")
    git(repo, "checkout", "-b", "work")
    return repo


def run(repo: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "BASE_REF": "origin/base",
        "GATES": "ruff-check ruff-format pytest",
        "PY_RUN": "python -m",
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        "PYTEST_ARGS": "-q -p no:randomly --rootdir=.",
    }
    return subprocess.run(
        [BASH, "scripts/migration/python_gate_baseline.sh"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_preexisting_failure_passes(tmp_path):
    result = run(make_repo(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "ruff-check" in result.stdout


def test_new_ruff_error_fails(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "app" / "new.py").write_text("import sys\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "new error")
    result = run(repo)
    assert result.returncode == 1
    assert "new failures" in result.stderr
    assert "app/new.py" in result.stderr.replace("\\", "/")


def test_new_pytest_failure_fails(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "tests" / "test_b.py").write_text(
        "def test_b():\n    assert False\n", encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "new failing test")
    result = run(repo)
    assert result.returncode == 1
    assert "test_b" in result.stderr
