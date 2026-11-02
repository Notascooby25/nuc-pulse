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
