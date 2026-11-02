"""Check a pull request has a changelog entry and a filled-in change record.

Run by .github/workflows/change-record.yml. Reads the pull request from the
event file GitHub provides; the description is only ever read as text.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HEADINGS = (
    "What you asked for",
    "What was decided",
    "What changed",
    "Checked",
    "Not checked",
    "Go-ahead",
)
SKIP_LABEL = "no-changelog"
SHA = re.compile(r"[0-9a-f]{40}")


def sections(body: str) -> dict[str, str]:
    """Map each '## Heading' to the text under it, with HTML comments removed."""
    text = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.DOTALL)
    found: dict[str, str] = {}
    current = None
    for line in text.split("\n"):
        match = re.match(r"##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1)
            found.setdefault(current, "")
        elif current is not None:
            found[current] += line.strip()
    return found


def changelog_changed(base: str, head: str) -> bool:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}", "--"],
        capture_output=True, text=True, check=True,
    )
    return "CHANGELOG.md" in out.stdout.split("\n")


def main() -> int:
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        pr = json.load(f)["pull_request"]
    problems = []

    labels = {label.get("name") for label in pr.get("labels") or []}
    if SKIP_LABEL not in labels:
        base = (pr.get("base") or {}).get("sha") or ""
        head = (pr.get("head") or {}).get("sha") or ""
        if not (SHA.fullmatch(base) and SHA.fullmatch(head)):
            problems.append("Couldn't read the pull request's commits to compare.")
        else:
            try:
                if not changelog_changed(base, head):
                    problems.append(
                        "CHANGELOG.md hasn't been updated. Add an entry for this "
                        f"release, or add the '{SKIP_LABEL}' label for a docs-only "
                        "or tiny change."
                    )
            except subprocess.CalledProcessError:
                problems.append("Couldn't compare the commits to find a CHANGELOG.md change.")

    found = sections(pr.get("body") or "")
    for heading in HEADINGS:
        if heading not in found:
            problems.append(f"The change record is missing the '{heading}' heading.")
        elif not found[heading]:
            problems.append(f"The change record's '{heading}' heading is empty.")

    if problems:
        print("This pull request isn't ready to merge:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Changelog and change record are in place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
