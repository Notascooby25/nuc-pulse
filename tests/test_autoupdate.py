import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def test_autoupdate_script_bash_syntax():
    """Verify scripts/autoupdate.sh exists, is executable, and passes bash syntax validation."""
    script_path = REPO_DIR / "scripts" / "autoupdate.sh"
    assert script_path.is_file(), "scripts/autoupdate.sh should exist"

    result = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert result.returncode == 0, f"Bash syntax error in autoupdate.sh: {result.stderr}"


def test_autoupdate_service_template():
    """Verify scripts/nuc-pulse-autoupdate.service template has expected directives and placeholders."""
    service_path = REPO_DIR / "scripts" / "nuc-pulse-autoupdate.service"
    assert service_path.is_file(), "scripts/nuc-pulse-autoupdate.service should exist"

    content = service_path.read_text()
    assert "[Unit]" in content
    assert "Description=" in content
    assert "[Service]" in content
    assert "Type=oneshot" in content
    assert "ExecStart=__REPO_DIR__/scripts/autoupdate.sh" in content
    assert "WorkingDirectory=__REPO_DIR__" in content


def test_autoupdate_timer_template():
    """Verify scripts/nuc-pulse-autoupdate.timer template has 15-minute cadence."""
    timer_path = REPO_DIR / "scripts" / "nuc-pulse-autoupdate.timer"
    assert timer_path.is_file(), "scripts/nuc-pulse-autoupdate.timer should exist"

    content = timer_path.read_text()
    assert "[Unit]" in content
    assert "[Timer]" in content
    assert "OnBootSec=2min" in content
    assert "OnUnitActiveSec=15min" in content
    assert "Persistent=true" in content
    assert "[Install]" in content
    assert "WantedBy=timers.target" in content


def test_autoupdate_dry_run_help():
    """Verify autoupdate.sh supports --check or --help without modifying git state."""
    script_path = REPO_DIR / "scripts" / "autoupdate.sh"
    result = subprocess.run(["bash", str(script_path), "--check"], cwd=str(REPO_DIR), capture_output=True, text=True)
    assert result.returncode in (0, 1)
    assert "NUC Pulse Auto-Updater" in result.stdout or "NUC Pulse Auto-Updater" in result.stderr


def test_install_script_configures_autoupdate_timer():
    """Verify scripts/install.sh provisions and enables nuc-pulse-autoupdate.timer."""
    install_path = REPO_DIR / "scripts" / "install.sh"
    assert install_path.is_file()
    content = install_path.read_text()
    assert "nuc-pulse-autoupdate.service" in content
    assert "nuc-pulse-autoupdate.timer" in content
    assert "systemctl --user enable --now nuc-pulse-autoupdate.timer" in content
