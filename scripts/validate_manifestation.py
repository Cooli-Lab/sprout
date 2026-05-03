"""Post-genesis validation — defense-in-depth on the AI's actual output.

This runs AFTER Claude has finished writing files and the
claude-code-action wrapper has committed them to a `claude/*` branch
and (typically) opened a PR.

It is the load-bearing security layer. Even if the AI is jailbroken via
prompt injection in the issue body, this step inspects the real diff and
enforces the laws by file mode, path, and size — none of which Claude can
talk its way around.

Order of operations:
  1. If `.genesis/refused.txt` exists → relay the refusal, close the issue.
  2. Find the PR the action just opened.
  3. Enumerate the diff via `git`.
  4. Reject on: forbidden paths, path traversal, symlinks, submodules,
     oversized files, too many files.
  5. If clean, squash-merge and close the issue with success.
  6. Fail closed on any unexpected error (the workflow exits non-zero
     and the PR remains open and unmerged for human review).
"""
import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone

from github import Github, GithubException

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO_NAME = os.environ["REPOSITORY"]
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])
WORKFLOW_STARTED = os.environ.get("WORKFLOW_STARTED", "")  # ISO 8601, optional

FORBIDDEN_PREFIXES = (".github/", "scripts/", ".genesis/")
FORBIDDEN_FILES = {"README.md", "CLAUDE.md", "requirements.txt", ".gitignore"}
ALLOWED_MODES = {"100644", "100755"}  # regular file / executable

MAX_FILE_BYTES = 1_000_000     # 1 MB per file
MAX_TOTAL_BYTES = 5_000_000    # 5 MB total
MAX_FILE_COUNT = 50

REFUSED_FILE = ".genesis/refused.txt"


def main():
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    issue = repo.get_issue(ISSUE_NUMBER)

    # Stage 1: explicit refusal from the Builder. Per CLAUDE.md, the file
    # contains a 1-2 line roast that becomes the comment body.
    if os.path.exists(REFUSED_FILE):
        with open(REFUSED_FILE, encoding="utf-8") as f:
            roast = f.read().strip() or "no reason given"
        seal_issue(issue, f"🛑 *Genesis Refused.*\n\n{roast}")
        return

    # Stage 2: find the PR
    pr = find_genesis_pr(repo)
    if pr is None:
        seal_issue(issue, "⚠️ **Genesis Failed:** No manifestation was produced.")
        return

    # Stage 3: enumerate changes
    head_ref = pr.head.ref
    try:
        files = changed_files(head_ref)
    except subprocess.CalledProcessError:
        refuse(pr, issue, "⚠️ **Genesis Failed:** Could not inspect the manifestation.")
        return

    if not files:
        refuse(pr, issue, "⚠️ **Genesis Failed:** The void was unchanged — nothing was written.")
        return

    if len(files) > MAX_FILE_COUNT:
        refuse(pr, issue, f"🛑 **Genesis Refused:** Manifestation exceeded the file limit ({len(files)} > {MAX_FILE_COUNT}).")
        return

    # Stage 4: validate each file
    total_bytes = 0
    for entry in files:
        path = entry["path"]
        status = entry["status"]

        if path in FORBIDDEN_FILES:
            refuse(pr, issue, f"🛑 **Genesis Refused:** A foundational file was attempted (`{path}`). The bones cannot rewrite themselves.")
            return
        if any(path.startswith(p) for p in FORBIDDEN_PREFIXES):
            refuse(pr, issue, f"🛑 **Genesis Refused:** A foundational path was attempted (`{path}`). The bones cannot rewrite themselves.")
            return
        if path.startswith("/") or ".." in path.split("/"):
            refuse(pr, issue, f"🛑 **Genesis Refused:** Path traversal attempted (`{path}`).")
            return

        if status.startswith("D"):
            continue  # deletion: nothing to type-check

        info = file_info(f"origin/{head_ref}", path)
        if info is None:
            continue
        if info["mode"] not in ALLOWED_MODES:
            refuse(pr, issue, f"🛑 **Genesis Refused:** Forbidden file type (`{path}`, mode `{info['mode']}`). Symlinks and submodules are not allowed.")
            return

        size = file_size(info["hash"])
        if size > MAX_FILE_BYTES:
            refuse(pr, issue, f"🛑 **Genesis Refused:** A single file exceeded the size limit (`{path}`, {size:,} bytes > {MAX_FILE_BYTES:,}).")
            return
        total_bytes += size

    if total_bytes > MAX_TOTAL_BYTES:
        refuse(pr, issue, f"🛑 **Genesis Refused:** Total manifestation too large ({total_bytes:,} > {MAX_TOTAL_BYTES:,} bytes).")
        return

    # Stage 5: merge and seal
    try:
        pr.merge(merge_method="squash", commit_message=f"Genesis: manifest from Issue #{ISSUE_NUMBER}")
    except GithubException as e:
        msg = e.data.get("message", str(e.status)) if isinstance(e.data, dict) else str(e.status)
        refuse(pr, issue, f"⚠️ **Genesis Failed:** Merge could not be completed ({msg}).")
        return

    issue.create_comment("✨ **Genesis Complete:** The void has shape.")
    issue.edit(state="closed")


def find_genesis_pr(repo):
    """Find the PR the claude-code-action just opened.

    The action's default branch prefix is ``claude/``. We rely on the
    workflow's per-architect concurrency lock to ensure that the most
    recent open PR with that prefix belongs to this run.

    If WORKFLOW_STARTED is provided (ISO 8601), only PRs created after
    that timestamp are considered, which makes the heuristic stricter.
    """
    threshold = None
    if WORKFLOW_STARTED:
        try:
            threshold = datetime.fromisoformat(WORKFLOW_STARTED.replace("Z", "+00:00")) - timedelta(minutes=5)
        except ValueError:
            threshold = None

    for pr in repo.get_pulls(state="open", sort="created", direction="desc"):
        ref = pr.head.ref
        if not (ref.startswith("claude/") or ref.startswith("genesis/")):
            continue
        if threshold and pr.created_at.replace(tzinfo=timezone.utc) < threshold:
            continue
        return pr
    return None


def changed_files(head_ref):
    subprocess.run(["git", "fetch", "origin", head_ref], check=True, capture_output=True)
    result = subprocess.run(
        ["git", "diff", f"origin/main...origin/{head_ref}", "--name-status"],
        check=True, capture_output=True, text=True,
    )
    files = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        files.append({"status": parts[0], "path": parts[-1]})
    return files


def file_info(ref, path):
    result = subprocess.run(
        ["git", "ls-tree", ref, path],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    head = result.stdout.split("\t", 1)[0]
    parts = head.split()
    if len(parts) < 3:
        return None
    return {"mode": parts[0], "type": parts[1], "hash": parts[2]}


def file_size(blob_hash):
    result = subprocess.run(
        ["git", "cat-file", "-s", blob_hash],
        check=True, capture_output=True, text=True,
    )
    return int(result.stdout.strip())


def refuse(pr, issue, message):
    """Close the PR and seal the issue with a refusal comment."""
    try:
        pr.create_issue_comment("Closed by Genesis post-validation.")
        pr.edit(state="closed")
    except GithubException:
        pass
    seal_issue(issue, message)


def seal_issue(issue, message):
    issue.create_comment(message)
    issue.edit(state="closed")
    sys.exit(0)


if __name__ == "__main__":
    main()
