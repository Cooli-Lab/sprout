"""Prepend a row to MANIFESTATIONS.md after a successful Genesis.

Triggered by the workflow after `validate_manifestation.py` merges the
genesis PR (which writes `.genesis/merged.txt` with the PR number).
Pulls metadata via the GitHub API, builds a one-line entry, prepends
it to the markdown table, and writes the file back. The workflow
commits the result directly to `main`.

This script is idempotent — if the same PR is already at the top of
the table, it's a no-op.

Decree polish: if GEMINI_API_KEY is set, the raw issue title is
re-cast through Gemini into a short, professional product-style name
(e.g. "a tool to help organize clients leads" → "Lead Organizer").
Without the key, the original title is used.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urlrequest

from github import Github

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO_NAME = os.environ["REPOSITORY"]

LOG_FILE = Path("MANIFESTATIONS.md")
MERGED_FLAG = Path(".genesis/merged.txt")

HEADER = """# Manifestations

A running log of what's been manifested in the [Sprout](./README.md). Newest first.
Visible at [cooli.ai/sprouts](https://cooli.ai/sprouts/) (gallery) or
[cooli-lab.github.io/sprout](https://cooli-lab.github.io/sprout/) (direct).

| Date | Architect | Decree | Path | Issue | PR | Files |
|---|---|---|---|---|---|---|
"""


POLISH_PROMPT = (
    "You are renaming a manifested project from a public AI experiment "
    "(Cooli Lab Sprout). The input is a GitHub Issue title written by "
    "a human — often informal, description-style, or grammatically rough. "
    "Optional context: the project's directory name and a snippet of the "
    "showcase page that was generated for it.\n\n"
    "Output a SHORT, professional product-style name for the project.\n\n"
    "Strict rules:\n"
    "- Output ONLY the name. No quotes. No prefixes. No JSON. No explanation.\n"
    "- 1 to 4 words. Title Case. ASCII only.\n"
    "- Concrete and specific. Avoid generic words alone (\"AI Tool\", "
    "\"App\", \"Helper\").\n"
    "- Should sound like a real product page title.\n"
    "- Do not invent functionality not implied by the input.\n"
    "- If the input is already a clean Title-Case product name (≤4 words, "
    "no leading article, capitalized), return it unchanged.\n\n"
    "Examples:\n"
    "\"a tool to help organize clients leads\" → Lead Organizer\n"
    "\"A python Minecraft server proxy\" → Minecraft Server Gateway\n"
    "\"build a markdown to slides converter\" → Markdown Slides\n"
    "\"i want a thing that summarizes RSS feeds\" → RSS Digest\n"
    "\"Lead Organizer\" → Lead Organizer\n"
)


def polish_decree(title, project_path="", showcase_excerpt=""):
    """Re-cast a raw issue title as a professional product name via
    Gemini. Falls back to the original title if no key, network error,
    or any unexpected response shape. Always safe."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not title or not title.strip():
        return title
    model = os.environ.get("GEMINI_POLISH_MODEL", "gemini-2.5-flash-lite")
    user_parts = [f"Issue title: {title.strip()}"]
    if project_path:
        user_parts.append(f"Project directory: {project_path}")
    if showcase_excerpt:
        user_parts.append(f"Showcase excerpt:\n{showcase_excerpt[:600]}")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "\n".join(user_parts)}]}],
        "systemInstruction": {"parts": [{"text": POLISH_PROMPT}]},
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 60,
        },
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    try:
        req = urlrequest.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        polished = "".join(p.get("text", "") for p in parts).strip()
        # Sanitize: strip quotes, collapse whitespace, enforce length.
        polished = polished.strip().strip('"\'').strip()
        polished = re.sub(r"\s+", " ", polished)
        if not polished or len(polished) > 60 or "\n" in polished:
            return title
        # If the model rejected and echoed something explanatory, fall back.
        if polished.lower().startswith(("here is", "i ", "the ", "name:", "title:")):
            return title
        return polished
    except Exception as e:
        print(f"[polish] {type(e).__name__}: {e} — using raw title", file=sys.stderr)
        return title


def _read_showcase_excerpt(project_path):
    """Read the project's showcase page (if any) for naming context."""
    if not project_path or project_path == ".":
        return ""
    p = Path(project_path) / "index.html"
    if not p.exists():
        return ""
    try:
        text = p.read_text(errors="ignore")
        # Strip tags loosely.
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:600]
    except Exception:
        return ""


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

    # Pick a project directory: most common top-level directory in the diff.
    # Falls back to "." if everything was committed at the repo root.
    from collections import Counter
    top_dirs = [p.split("/", 1)[0] for p in file_paths if "/" in p]
    project_path = Counter(top_dirs).most_common(1)[0][0] if top_dirs else "."

    date = (pr.merged_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")

    architect_cell = "—"
    decree_cell = "—"
    issue_cell = "—"
    if issue_num:
        issue = repo.get_issue(issue_num)
        login = issue.user.login if issue.user else "unknown"
        architect_cell = f"[@{login}](https://github.com/{login})"
        raw_title = (issue.title or "").replace("[Manifest]", "").strip()
        showcase_excerpt = _read_showcase_excerpt(project_path)
        polished = polish_decree(raw_title, project_path=project_path, showcase_excerpt=showcase_excerpt)
        if polished != raw_title:
            print(f"[polish] '{raw_title}' → '{polished}'")
        decree_cell = (polished[:80] + "…") if len(polished) > 80 else (polished or "—")
        # Escape pipe characters that would break the markdown table
        decree_cell = decree_cell.replace("|", "\\|")
        issue_cell = f"[#{issue_num}](https://github.com/{REPO_NAME}/issues/{issue_num})"

    pr_cell = f"[#{pr.number}](https://github.com/{REPO_NAME}/pull/{pr.number})"
    path_cell = f"`{project_path}`"

    new_row = f"| {date} | {architect_cell} | {decree_cell} | {path_cell} | {issue_cell} | {pr_cell} | {files_cell} |"

    if LOG_FILE.exists():
        existing = LOG_FILE.read_text()
        if new_row in existing:
            print(f"Entry for PR #{pr.number} already in log — skipping.")
            return
        # Find the table separator and insert the new row right below it.
        sep_re = re.compile(r"^\|(\s*-+\s*\|){4,}", re.MULTILINE)
        if sep_re.search(existing):
            lines = existing.splitlines()
            for i, line in enumerate(lines):
                if sep_re.match(line):
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
