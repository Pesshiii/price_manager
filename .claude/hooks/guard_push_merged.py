"""PreToolUse guard: ask before pushing to a branch whose pull request already merged.

PRs here are squash-merged, so a commit pushed to the branch afterwards reaches
nothing: the PR is closed, `main` holds a squash of the old head, and the new
commit sits on a branch nobody will look at again. #200 is the worked example —
a follow-up pushed to #199's branch after auto-merge took it, found only because
the feature was visibly missing. With `delete_branch_on_merge` on, the push does
not even fail: it recreates the deleted branch, with no PR attached.

The fix is a new branch from `origin/main` and a new PR. This hook asks when the
branch being pushed has a merged PR and no open one.

Deliberate scope limits, all fail-open:

- **One `gh` call per push**, not per Bash call: everything that is not a
  `git push` returns before the network.
- **`gh` missing, unauthenticated, offline or slow** → silent. A guard that
  blocks pushing when GitHub is unreachable costs more than the case it catches.
- **Deletes, tags and pushes to `main`** are not branch work and stay silent.
- **Only the first `git push` in a compound command is read.** Two pushes in one
  command is not something anyone writes.
"""
import json
import os
import re
import shlex
import subprocess
import sys

# Same rule as guard_branch_switch.py: `git` must start a command, so
# `grep -rn 'git push'` stays silent.
CMD = r"(?:^|[\n;&|(])\s*git\s+"
PUSH = re.compile(CMD + r"push\b([^;&|\n]*)")

# Options whose value is the next word, so it is not mistaken for a remote or refspec.
OPTS_WITH_VALUE = {"--repo", "--receive-pack", "--exec", "-o", "--push-option"}
SKIP_FLAGS = {"-d", "--delete", "--tags", "--all", "--mirror", "--prune"}

REASON = (
    "Branch `{branch}` belongs to PR #{number}, which is already **merged**, and "
    "it has no open PR. PRs here are squash-merged, so a commit pushed now never "
    "reaches `main` — #200 recovered a follow-up lost exactly this way after #199 "
    "auto-merged.\n\n"
    "Put the change on a new branch from `origin/main` and open a new PR. Approve "
    "this only if you mean to reuse the branch name for a new PR."
)


def ask(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))


def run(args: list[str], cwd: str) -> str | None:
    try:
        out = subprocess.run(args, cwd=cwd or None, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def pushed_branch(tail: str, cwd: str) -> str | None:
    """The remote branch this `git push` writes to, or None if it is not branch work."""
    try:
        words = shlex.split(tail)
    except ValueError:
        words = tail.split()

    positional, skip_next = [], False
    for w in words:
        if skip_next:
            skip_next = False
            continue
        if w in SKIP_FLAGS:
            return None
        if w in OPTS_WITH_VALUE:
            skip_next = True
            continue
        if w.startswith("-"):
            continue
        positional.append(w)

    # positional[0] is the remote; the rest are refspecs. Read the first refspec,
    # or the current branch when there is none.
    ref = positional[1] if len(positional) > 1 else "HEAD"
    dst = ref.lstrip("+").split(":")[-1]
    if not dst or dst == "HEAD":
        dst = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd) or ""
    dst = dst.removeprefix("refs/heads/")
    if not dst or dst == "HEAD" or dst == "main" or dst.startswith("refs/tags/"):
        return None
    return dst


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    command = (payload.get("tool_input") or {}).get("command", "")
    push = PUSH.search(command) if command else None
    if not push:
        return
    cwd = payload.get("cwd") or os.getcwd()

    branch = pushed_branch(push.group(1), cwd)
    if not branch:
        return

    listed = run(
        ["gh", "pr", "list", "--head", branch, "--state", "all", "--limit", "20",
         "--json", "number,state"],
        cwd,
    )
    try:
        prs = json.loads(listed) if listed else []
    except ValueError:
        return
    if any(pr.get("state") == "OPEN" for pr in prs):
        return
    merged = [pr["number"] for pr in prs if pr.get("state") == "MERGED"]
    if merged:
        ask(REASON.format(branch=branch, number=max(merged)))


if __name__ == "__main__":
    main()
