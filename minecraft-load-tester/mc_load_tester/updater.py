"""
updater
=======

Механизм самообновления через git. Позволяет установленной копии получать
изменения из репозитория (когда автор что-то поправил) командой ``git pull``,
а веб-серверу -- по желанию проверять и применять обновления автоматически.

Все функции безопасны при отсутствии git или при том, что каталог не является
git-репозиторием: в этом случае возвращается ``is_git = False`` без исключений.
"""

from __future__ import annotations

import os
import subprocess


def _git(args, cwd, timeout=60):
    """Выполнить git-команду, вернуть (код, stdout, stderr). -1 если git нет."""
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)


def repo_root(cwd: str) -> str | None:
    """Корень git-репозитория, содержащего ``cwd`` (или None)."""
    code, out, _ = _git(["rev-parse", "--show-toplevel"], cwd)
    return out if code == 0 and out else None


def is_git_repo(cwd: str) -> bool:
    return repo_root(cwd) is not None


def current_commit(cwd: str) -> str | None:
    code, out, _ = _git(["rev-parse", "--short", "HEAD"], cwd)
    return out if code == 0 else None


def current_branch(cwd: str) -> str | None:
    code, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return out if code == 0 else None


def behind_count(cwd: str) -> int | None:
    """Насколько локальная ветка отстаёт от upstream (или None, если неизвестно)."""
    code, out, _ = _git(["rev-list", "--count", "HEAD..@{u}"], cwd)
    if code != 0:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def status(cwd: str, fetch: bool = False) -> dict:
    """Сводка состояния обновлений.

    :param fetch: если True -- сначала ``git fetch`` (обращение к сети).
    """
    if not is_git_repo(cwd):
        return {"is_git": False}
    if fetch:
        _git(["fetch", "--quiet"], cwd)
    behind = behind_count(cwd)
    return {
        "is_git": True,
        "commit": current_commit(cwd),
        "branch": current_branch(cwd),
        "behind": behind,
        "update_available": bool(behind),
    }


def pull(cwd: str) -> dict:
    """Применить обновления (``git pull --ff-only``).

    :returns: словарь ``{ok, message, updated, commit}``.
    """
    if not is_git_repo(cwd):
        return {"ok": False, "message": "Каталог не является git-репозиторием.", "updated": False}
    before = current_commit(cwd)
    code, out, err = _git(["pull", "--ff-only"], cwd, timeout=120)
    if code != 0:
        return {"ok": False, "message": err or out or "git pull не удался", "updated": False}
    after = current_commit(cwd)
    return {
        "ok": True,
        "message": out or "Готово",
        "updated": before != after,
        "commit": after,
    }


def project_dir() -> str:
    """Каталог проекта (родитель пакета ``mc_load_tester``)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
