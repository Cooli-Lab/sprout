"""Pre-genesis validation — gate on architect identity and quotas.

Checks (in order):
  1. Idempotency — has the issue already been picked up?
  2. Issue body sanity — non-empty, under length cap.
  3. Optional allowlist — if GENESIS_ALLOWLIST is set, only those logins pass.
  4. Architect type — bot accounts are turned away.
  5. Account age — must exceed MIN_ACCOUNT_AGE.
  6. Account activity — at least one public repo OR one follower.
  7. Quota — at most MAX_ISSUES total per architect.
  8. Cooldown — at least COOLDOWN since the most recent prior issue.

On any failure: comments + closes the issue, writes proceed=false, exits 0.
On success: tags the issue with the processing label, writes proceed=true.
The workflow fails closed on any uncaught exception.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from github import Github, GithubException

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO_NAME = os.environ["REPOSITORY"]
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])
AUTHOR_LOGIN = os.environ["AUTHOR_LOGIN"]
GH_OUTPUT = os.environ.get("GITHUB_OUTPUT")
ALLOWLIST = {s.strip() for s in os.environ.get("GENESIS_ALLOWLIST", "").split(",") if s.strip()}

MAX_ISSUES = 3
COOLDOWN = timedelta(hours=24)
MIN_ACCOUNT_AGE = timedelta(days=30)
MAX_BODY_CHARS = 8000
PROCESSING_LABEL = "genesis-processing"


def main():
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    issue = repo.get_issue(ISSUE_NUMBER)

    # 1. Idempotency
    if any(label.name == PROCESSING_LABEL for label in issue.labels):
        print(f"Issue #{ISSUE_NUMBER} already bears the {PROCESSING_LABEL} label; halting.")
        emit("proceed", "false")
        return

    # 2. Issue body sanity
    body = issue.body or ""
    if not body.strip():
        deny(issue, "🛑 **Genesis Failed:** Your issue has no body. Describe what you want manifested.")
    if len(body) > MAX_BODY_CHARS:
        deny(issue, f"🛑 **Genesis Failed:** Your issue body exceeds the limit ({len(body):,} > {MAX_BODY_CHARS:,} characters).")

    # 3. Allowlist
    if ALLOWLIST and AUTHOR_LOGIN not in ALLOWLIST:
        deny(issue, "🛑 **Genesis Failed:** This sandbox is currently restricted to allowlisted architects.")

    user = g.get_user(AUTHOR_LOGIN)

    # 4. Architect must be human
    if user.type == "Bot" or AUTHOR_LOGIN.endswith("[bot]"):
        deny(issue, "🛑 **Genesis Failed:** Only human architects may shape this void.")

    # 5. Account age
    age = datetime.now(timezone.utc) - user.created_at.replace(tzinfo=timezone.utc)
    if age < MIN_ACCOUNT_AGE:
        deny(issue, "🛑 **Genesis Failed:** Your GitHub account must be at least 30 days old to shape the void.")

    # 6. Account activity (filter freshly-stockpiled accounts)
    if user.public_repos == 0 and user.followers == 0:
        deny(issue, "🛑 **Genesis Failed:** Your account shows no public activity. Build something visible elsewhere first.")

    # 7+8. Quota and cooldown
    query = f"repo:{REPO_NAME} type:issue author:{AUTHOR_LOGIN}"
    prior = [i for i in g.search_issues(query, sort="created", order="desc") if i.number != ISSUE_NUMBER]

    if len(prior) >= MAX_ISSUES:
        deny(issue, f"🛑 **Genesis Failed:** You have reached the absolute limit of {MAX_ISSUES} creations. Your work here is done.")

    if prior:
        elapsed = datetime.now(timezone.utc) - prior[0].created_at.replace(tzinfo=timezone.utc)
        if elapsed < COOLDOWN:
            remaining = int((COOLDOWN - elapsed).total_seconds() // 3600) + 1
            deny(issue, f"⏳ **Genesis Failed:** Observe the 24-hour day of rest before creating again. Return in ~{remaining} hour(s).")

    ensure_label(repo, PROCESSING_LABEL)
    issue.add_to_labels(PROCESSING_LABEL)
    print("Architect verified. Proceeding to genesis.")
    emit("proceed", "true")


def deny(issue, message):
    issue.create_comment(message)
    issue.edit(state="closed")
    print(f"Denied: {message[:100]}")
    emit("proceed", "false")
    sys.exit(0)


def ensure_label(repo, name):
    try:
        repo.create_label(name=name, color="6e5494", description="Issue is being processed by the Genesis Builder")
    except GithubException as e:
        if e.status != 422:
            raise


def emit(key, value):
    if GH_OUTPUT:
        with open(GH_OUTPUT, "a") as f:
            f.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
