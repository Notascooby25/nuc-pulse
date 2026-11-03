"""Run scripts/preview.sh from a throw-away copy of the repo to check how it handles a busy port."""

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "preview.sh"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "preview.sh")
    return tmp_path


@pytest.fixture
def busy_port():
    """A listener standing in for something already using the preview port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    yield sock
    sock.close()


def _run(repo, port, cmd):
    env = {**os.environ, "NUC_PULSE_PREVIEW_PORT": str(port)}
    return subprocess.run(["bash", str(repo / "scripts" / "preview.sh"), cmd], cwd=repo,
                          env=env, capture_output=True, text=True, timeout=30)


def test_up_refuses_when_port_busy(repo, busy_port):
    pid_file = repo / ".preview.pid"
    pid_file.write_text("999999\n")
    result = _run(repo, busy_port.getsockname()[1], "up")
    assert result.returncode != 0
    assert "already in use" in result.stdout
    assert pid_file.read_text() == "999999\n"


def test_status_reports_untracked_listener(repo, busy_port):
    result = _run(repo, busy_port.getsockname()[1], "status")
    assert "in use" in result.stdout
    assert "STOPPED" not in result.stdout


def test_down_leaves_foreign_process_alone(repo, busy_port):
    port = busy_port.getsockname()[1]
    _run(repo, port, "down")
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass
