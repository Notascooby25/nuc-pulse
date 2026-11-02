from src.sanitizer import sanitize_text


def test_redacts_healthcheck_urls_and_secrets():
    raw = (
        "Pinging https://hc-ping.com/a1b2c3d4-e5f6-7890-abcd-1234567890ab\n"
        "Connecting to postgresql://postgres:supersecret@db:5432/sleepdb\n"
        "WATCHTOWER_NOTIFICATION_URL=https://hooks.slack.com/services/T00/B00/X00\n"
        "SPOTIFY_CLIENT_SECRET=my_secret_val token=abc123xyz"
    )
    cleaned = sanitize_text(raw)
    assert "a1b2c3d4" not in cleaned
    assert "hc-ping.com/<redacted>" in cleaned
    assert "supersecret" not in cleaned
    assert "my_secret_val" not in cleaned
    assert "abc123xyz" not in cleaned
