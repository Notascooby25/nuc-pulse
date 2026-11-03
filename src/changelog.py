import re
from pathlib import Path

VERSION_HEADING = re.compile(r"^## (\S+) - (\S+)")


def latest_release(path: Path) -> dict | None:
    """Return the newest CHANGELOG.md entry as {version, date, changes}, or None."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    release = None
    for line in lines:
        if release is None:
            match = VERSION_HEADING.match(line)
            if match:
                release = {"version": match.group(1), "date": match.group(2), "changes": []}
            continue
        if line.startswith("## "):
            break
        if line.startswith("- "):
            release["changes"].append(line[2:].strip())
        elif line[:1].isspace() and line.strip() and release["changes"]:
            # Indented continuation of the previous bullet
            release["changes"][-1] += " " + line.strip()
    return release
