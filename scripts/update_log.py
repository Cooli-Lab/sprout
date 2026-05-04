"""Prepend a row to MANIFESTATIONS.md after a successful Genesis.

Triggered by the workflow after `validate_manifestation.py` merges the
genesis PR (which writes `.genesis/merged.txt` with the PR number).
Pulls metadata via the GitHub API, builds a one-line entry, prepends
it to the markdown table, and writes the file back. The workflow
commits the result directly to `main`.

This script is idempotent — if the same PR is already at the top of
the table, it's a no-op.
"""
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from github import Github

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO_NAME = os.environ["REPOSITORY"]

LOG_FILE = Path("MANIFESTATIONS.md")
MERGED_FLAG = Path(".genesis/merged.txt")

HEADER = """# Manifestations

A running log of what's been manifested in the [Sprout](./README.md). Newest first.

| Date | Architect | Decree | Issue | PR | Files |
|---|---|---|---|---|---|
"""


def main():
    if not MERGED_FLAG.exists():
        print("No merge flag — nothing to log.")
        return
    pr_number = int(MERGED_FLAG.read_text().strip())

    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    pr = repo.get_pull(pr_number)

    # Find the originating issue by parsing the PR body
    issue_num = None
    m = re.search(r"Issue #(\d+)", pr.body or "")
    if m:
        issue_num = int(m.group(1))

    # Collect non-removed file paths from the merged PR
    file_paths = sorted({f.filename for f in pr.get_files() if f.status != "removed"})
    files_cell = ", ".join(f"`{p}`" for p in file_paths[:4])
    if len(file_paths) > 4:
        files_cell += f" (+{len(file_paths) - 4} more)"
    if not files_cell:
        files_cell = "—"

    date = (pr.merged_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")

    architect_cell = "—"
    decree_cell = "—"
    issue_cell = "—"
    if issue_num:
        issue = repo.get_issue(issue_num)
        login = issue.user.login if issue.user else "unknown"
        architect_cell = f"[@{login}](https://github.com/{login})"
        title = (issue.title or "").replace("[Manifest]", "").strip()
        decree_cell = (title[:80] + "…") if len(title) > 80 else (title or "—")
        # Escape pipe characters that would break the markdown table
        decree_cell = decree_cell.replace("|", "\\|")
        issue_cell = f"[#{issue_num}](https://github.com/{REPO_NAME}/issues/{issue_num})"

    pr_cell = f"[#{pr.number}](https://github.com/{REPO_NAME}/pull/{pr.number})"

    new_row = f"| {date} | {architect_cell} | {decree_cell} | {issue_cell} | {pr_cell} | {files_cell} |"

    if LOG_FILE.exists():
        existing = LOG_FILE.read_text()
        if new_row in existing:
            print(f"Entry for PR #{pr.number} already in log — skipping.")
            return
        if "|---|---|" in existing:
            lines = existing.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("|---|---|"):
                    lines.insert(i + 1, new_row)
                    break
            content = "\n".join(lines) + ("\n" if not existing.endswith("\n") else "")
        else:
            # File exists but in unexpected shape — start a fresh table
            content = HEADER + new_row + "\n"
    else:
        content = HEADER + new_row + "\n"

    LOG_FILE.write_text(content)
    print(f"Logged PR #{pr.number}")


if __name__ == "__main__":
    main()
