import subprocess
from pathlib import Path

from glacies.pipeline import git_state


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


def test_scoped_state_ignores_changes_outside_the_paths(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "engine.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("notes\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "engine")
    engine_commit = git(tmp_path, "rev-parse", "HEAD")

    (tmp_path / "notes.md").write_text("more notes\n", encoding="utf-8")
    assert git_state(tmp_path, ["src"]) == (engine_commit, False)
    assert git_state(tmp_path)[1] is True  # the whole tree is dirty
    git(tmp_path, "commit", "-q", "-am", "docs")
    assert git_state(tmp_path, ["src"]) == (engine_commit, False)
    assert git_state(tmp_path)[0] != engine_commit

    (tmp_path / "src" / "engine.py").write_text("a = 2\n", encoding="utf-8")
    assert git_state(tmp_path, ["src"]) == (engine_commit, True)


def test_outside_a_repository_there_is_no_state(tmp_path: Path) -> None:
    assert git_state(tmp_path, ["src"]) == (None, None)
