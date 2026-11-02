from src.mock_data import get_mock_scenario
from src.report_builder import build_diagnostic_markdown


def test_build_diagnostic_markdown_degraded():
    state = get_mock_scenario("degraded")
    # Inject an IP (reserved documentation range) and a healthcheck URL to verify automatic scrubbing
    state["backups"]["offsite"][1]["log_tail"] += (
        "Connecting to 192.0.2.10 and pinging https://hc-ping.com/12345678-abcd-ef00\n"
    )
    md = build_diagnostic_markdown(state)

    assert "# NUC Pulse Diagnostic Report" in md
    assert "ATTENTION ITEMS" in md
    assert "Google Drive Sync" in md
    assert "UK Expense Tracker" in md
    assert "HTTP 500 Server Error" in md
    assert "3 security" in md
    # Verify redaction of private IP and secret URL
    assert "192.0.2.10" not in md
    assert "<redacted-ip>" in md
    assert "12345678-abcd-ef00" not in md
    assert "hc-ping.com/<redacted>" in md


def test_build_diagnostic_markdown_nominal():
    state = get_mock_scenario("nominal")
    md = build_diagnostic_markdown(state)

    assert "# NUC Pulse Diagnostic Report" in md
    assert "ALL SYSTEMS NOMINAL" in md
    assert "No failing or stale backups detected" in md
    assert "No unhealthy applications or containers detected" in md
