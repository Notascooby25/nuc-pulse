"""Run scripts/autoupdate.sh against throw-away git repos to check what it actually does."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parent.parent
SCRIPT = REPO_DIR / "scripts" / "autoupdate.sh"

FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "systemctl $*" >> "$CALLS"
exit 0
"""

# Records the requirements it was given and which commit the app was on at the time.
FAKE_PIP = """#!/usr/bin/env bash
req="${@: -2:1}"
for a in "$@"; do if [ "$prev" = "-r" ]; then req="$a"; fi; prev="$a"; done
echo "pip $(cat "$req" | tr '\\n' ' ')at $(git rev-parse --short HEAD)" >> "$CALLS"
exit "${PIP_EXIT:-0}"
"""


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def setup(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    nuc = tmp_path / "nuc"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "scripts").mkdir()
    shutil.copy(SCRIPT, work / "scripts" / "autoupdate.sh")
    (work / "requirements.txt").write_text("fastapi\n")
    (work / ".gitignore").write_text(".venv/\n")
    (work / "app.txt").write_text("v1\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "v1")
    _git(work, "push", "-q", "origin", "main")
    _git(tmp_path, "clone", "-q", str(origin), str(nuc))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "systemctl").write_text(FAKE_SYSTEMCTL)
    (bin_dir / "systemctl").chmod(0o755)
    (nuc / ".venv" / "bin").mkdir(parents=True)
    (nuc / ".venv" / "bin" / "pip").write_text(FAKE_PIP)
    (nuc / ".venv" / "bin" / "pip").chmod(0o755)

    calls = tmp_path / "calls.log"
    calls.touch()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PATH=f"{bin_dir}:{env['PATH']}", CALLS=str(calls))
    return {"work": work, "nuc": nuc, "calls": calls, "env": env}


def _publish(work, *, app="v2\n", requirements=None):
    (work / "app.txt").write_text(app)
    if requirements is not None:
        (work / "requirements.txt").write_text(requirements)
    _git(work, "commit", "-q", "-am", "update")
    _git(work, "push", "-q", "origin", "main")
    return _git(work, "rev-parse", "HEAD")


def _run(s, **extra):
    env = {**s["env"], **extra}
    return subprocess.run(["bash", str(s["nuc"] / "scripts" / "autoupdate.sh")],
                          cwd=s["nuc"], env=env, capture_output=True, text=True, timeout=60)


def test_updates_to_the_new_commit_and_restarts(setup):
    new = _publish(setup["work"])
    r = _run(setup)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(setup["nuc"], "rev-parse", "HEAD") == new
    assert "restart nuc-pulse.service" in setup["calls"].read_text()


def test_up_to_date_does_nothing(setup):
    r = _run(setup)
    assert r.returncode == 0
    assert "restart" not in setup["calls"].read_text()


def test_installs_new_requirements_before_updating_the_code(setup):
    old = _git(setup["nuc"], "rev-parse", "--short", "HEAD")
    _publish(setup["work"], requirements="fastapi\nhttpx\n")
    r = _run(setup)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"pip fastapi httpx at {old}" in setup["calls"].read_text()


def test_failed_requirements_install_keeps_the_old_code_and_retries(setup):
    old = _git(setup["nuc"], "rev-parse", "HEAD")
    new = _publish(setup["work"], requirements="fastapi\nhttpx\n")
    r = _run(setup, PIP_EXIT="1")
    assert r.returncode != 0
    assert _git(setup["nuc"], "rev-parse", "HEAD") == old
    assert "restart" not in setup["calls"].read_text()
    r = _run(setup)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(setup["nuc"], "rev-parse", "HEAD") == new


def test_never_makes_its_own_merge(setup, tmp_path):
    # A git set up to merge on pull, with an identity, as the NUC's could be.
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = n\n\temail = n@example.com\n[pull]\n\trebase = false\n")
    setup["env"]["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    (setup["nuc"] / "local.txt").write_text("local\n")
    _git(setup["nuc"], "add", "local.txt")
    _git(setup["nuc"], "commit", "-q", "-m", "local commit")
    local = _git(setup["nuc"], "rev-parse", "HEAD")
    _publish(setup["work"])
    r = _run(setup)
    assert r.returncode != 0
    assert _git(setup["nuc"], "rev-parse", "HEAD") == local
    assert "restart" not in setup["calls"].read_text()


def test_uncommitted_changes_are_left_alone(setup):
    _publish(setup["work"])
    (setup["nuc"] / "app.txt").write_text("edited on the NUC\n")
    r = _run(setup)
    assert r.returncode == 0
    assert (setup["nuc"] / "app.txt").read_text() == "edited on the NUC\n"
    assert "restart" not in setup["calls"].read_text()
