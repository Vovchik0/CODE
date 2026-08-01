"""Тесты самообновления через git (updater) на временных репозиториях."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from mc_load_tester import updater


def _git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True,
        env=dict(os.environ,
                 GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                 GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"),
    )


def _has_git():
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _has_git(), reason="git не установлен")


def _commit(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "add %s" % name], repo)


@pytest.fixture
def repos(tmp_path):
    """Создать upstream-репозиторий и его клон (work)."""
    up = str(tmp_path / "up")
    work = str(tmp_path / "work")
    os.makedirs(up)
    _git(["init", "-b", "main"], up)
    _commit(up, "a.txt", "A")
    _git(["clone", up, work], str(tmp_path))
    return up, work


def test_not_a_git_repo(tmp_path):
    plain = str(tmp_path / "plain")
    os.makedirs(plain)
    assert updater.is_git_repo(plain) is False
    st = updater.status(plain)
    assert st == {"is_git": False}
    res = updater.pull(plain)
    assert res["ok"] is False and res["updated"] is False


def test_status_and_pull_flow(repos):
    up, work = repos
    st = updater.status(work, fetch=True)
    assert st["is_git"] is True
    assert st["branch"] == "main"
    assert st["behind"] == 0
    assert st["update_available"] is False

    # Новый коммит в upstream -> клон отстаёт на 1.
    _commit(up, "b.txt", "B")
    st2 = updater.status(work, fetch=True)
    assert st2["behind"] == 1
    assert st2["update_available"] is True

    before = updater.current_commit(work)
    res = updater.pull(work)
    assert res["ok"] is True and res["updated"] is True
    assert res["commit"] != before
    assert os.path.exists(os.path.join(work, "b.txt"))

    # После обновления снова актуально.
    assert updater.status(work, fetch=True)["behind"] == 0
