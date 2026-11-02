# Changelog

What changed in each version, newest first, in plain English. One entry per release, added just before the owner's go-ahead.

## 0.2.1 - 2026-11-02
- Watchtowers no longer show a red cross for normal logs. A cross now means a real error or a failed update; warnings appear as a note.
- A note shows when a Watchtower is watching no containers.
- Watchtower log lines no longer start with stray characters.
- Audio Scrobbler is checked at its health-check address, so it no longer shows a false "HTTP 404".
- Backups made by hand or before a deploy or restore (`manual…`, `pre_…`) are shown as one-off copies instead of "stale". An empty one still shows a cross.

## 0.2.0 - 2026-11-02
- The auto-updater installs new dependencies before updating the code. If that fails, the working version stays in place and it tries again on the next run, instead of leaving new code without what it needs.
- The auto-updater only takes a straightforward update from GitHub. It never makes a merge of its own on the server; if the server's copy has drifted, it stops and says so.
- Every pull request now carries a change record and a changelog entry, checked on GitHub before merging.
- A test now uses an example address reserved for documentation instead of a real-looking one.

## 0.1.0 - 2026-11-02
- First version: a dashboard showing at a glance whether the server, apps, containers, Watchtower and backups are healthy, with details behind each tick or cross.
- Diagnostic report export with secrets and addresses scrubbed.
- Fedora update check, and the systemd service set up with the right folder.
- Background auto-updater that checks GitHub every 15 minutes.
