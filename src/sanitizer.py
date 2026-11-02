import re

# Redact healthchecks.io URLs (e.g. https://hc-ping.com/<uuid>)
RE_HCPING = re.compile(r"https?://hc-ping\.com/[A-Za-z0-9\-]+", re.IGNORECASE)

# Redact credentials inside connection strings (e.g. postgresql://user:pass@host)
RE_URI_CRED = re.compile(r"(://[^:/@\s]+):([^@\s]+)@", re.IGNORECASE)

# Redact key-value secrets (e.g. PASSWORD=xyz, SECRET=xyz, token=xyz)
RE_KV_SECRETS = re.compile(
    r"(\b[A-Za-z0-9_]*(?:PASSWORD|PASSWD|PASS|SECRET|TOKEN|APIKEY|API_KEY|KEY)\b\s*[:=]\s*)([^\s,;&\"']+)",
    re.IGNORECASE,
)

# Redact private / Tailscale / public IPv4 addresses except 127.0.0.1 and 0.0.0.0
RE_IPV4 = re.compile(r"\b(?!(?:127\.0\.0\.1|0\.0\.0\.0)\b)(?:\d{1,3}\.){3}\d{1,3}\b")


def sanitize_text(text: str) -> str:
    """Scrub sensitive credentials, tokens, and healthcheck URLs from logs or output."""
    if not text:
        return ""
    # 1. Healthchecks ping URLs
    cleaned = RE_HCPING.sub("https://hc-ping.com/<redacted>", text)
    # 2. Connection URIs with credentials
    cleaned = RE_URI_CRED.sub(r"\1:<redacted>@", cleaned)
    # 3. Key-value secrets
    cleaned = RE_KV_SECRETS.sub(r"\1<redacted>", cleaned)
    return cleaned


def sanitize_diagnostic_report(text: str) -> str:
    """Scrub secrets, tokens, healthcheck URLs, and non-loopback IPv4 addresses for safe sharing."""
    cleaned = sanitize_text(text)
    return RE_IPV4.sub("<redacted-ip>", cleaned)
