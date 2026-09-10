"""PreToolUse guard: keep concurrent agents out of each other's working tree.

Two Claude sessions in one checkout are not two workers, they are one working
tree with two writers. Agent B running `git checkout -b` re-points every file
under Agent A mid-edit — and because `docker-compose.yml` bind-mounts
`./price_manager:/app`, it re-points what the running container serves too, so
A's next test run silently exercises B's branch. `implement-issue` already knew
the single-agent half of this ("One issue per invocation ... a property of the
bind mount"); this is the multi-agent half.

The fix is a worktree per agent, and that lives in the skill. This is the net for
the paths that bypass the skill: an ad-hoc session, a `git switch` typed from
memory, a `reset --hard` reached for while cleaning up.

**Two rules, two different scopes.**

  * *Branch switching* is only dangerous in the **shared main checkout**. Inside a
    linked worktree it is ordinary work — that tree belongs to one agent — so the
    guard stays silent there. The discriminator needs no lock file and no session
    id: git already knows. `--git-dir` and `--git-common-dir` resolve to the same
    path in the main checkout and diverge in a linked worktree.

  * *Stashing* is dangerous **everywhere**, because the stash stack is a single
    stack shared by the main checkout and every worktree. A bare `git stash pop`
    can restore another session's work into your tree. Only the addressable forms
    are safe: `push -m <tag>` to create, `apply <sha>` to restore.

Both rules `ask` rather than `deny`, matching `guard_retiring_stack.py`. Switching
branches in the main checkout is completely legitimate when no one else is
working — and a hook cannot see who else is working. Asking puts that judgement
back with the person who can answer it.

Deliberate scope limits, all fail-open:

- **`git checkout -- <path>` is excluded.** That restores files and touches no
  branch. Over-firing on it would train the reflex to approve without reading,
  which costs more than the case it catches.
- **`git` must start a command, not just appear in one.** Unlike
  `guard_prod_data.py`, which matches on mention because it denies outright and
  rarely fires, this one asks and fires often, so precision is what keeps the
  prompt meaningful — `grep -rn 'git checkout'` stays silent. The gap is a switch
  hidden in backticks, which nobody writes.
- **Only the `Bash` tool passes through here.** Nothing else can move a branch.
- **The user's own terminal is invisible to hooks.** Gating the main checkout
  constrains agents only; a human types `git checkout` there unimpeded.
- **An unparseable payload or a failing `git` call stays silent** rather than
  blocking real work.
"""
import json
import os
import re
import shlex
import subprocess
import sys

# `git` must start a command, not merely appear in one. Without this,
# `grep -rn 'git checkout' .claude/` prompts — and a guard that fires while you
# are reading *about* these commands is one you learn to approve unread.
CMD = r"(?:^|[\n;&|(])\s*git\s+"

SWITCH = re.compile(CMD + r"(?:checkout|switch)\b")
RESET_HARD = re.compile(CMD + r"reset\b[^;&|]*\s--hard\b")
# `git checkout -- file` / `git checkout HEAD -- file`: a file restore, not a switch.
FILE_RESTORE = re.compile(CMD + r"checkout\b[^;&|]*\s--\s")
STASH = re.compile(CMD + r"stash\b([^;&|]*)")

# Stash subcommands that name what they act on, so they cannot take a sibling
# session's entry by accident.
SAFE_STASH_SUBCOMMANDS = {"list", "show", "apply", "drop", "branch", "clear"}

SWITCH_REASON = (
    "This changes branches in the **shared main checkout**, where another agent "
    "may be working. A branch switch re-points every file in the tree — and the "
    "container bind-mounts `./price_manager:/app`, so it re-points what the "
    "running app and the test suite serve as well.\n\n"
    "Work in a worktree of your own instead: `EnterWorktree`, which branches from "
    "`origin/main` and puts you in `.claude/worktrees/<name>/`. See step 3 of the "
    "`implement-issue` skill.\n\n"
    "Approve this only if you know no other agent is running — a solo session "
    "tidying up, or the user asked for this branch by name."
)

STASH_REASON = (
    "The stash stack is **shared** by the main checkout and every worktree, and a "
    "concurrent session may be pushing to it. `{form}` is not addressed to a "
    "specific entry, so it can bury or restore another agent's work.\n\n"
    "Use the addressable forms instead: `git stash push -u -m \"<unique-tag>\"` to "
    "create, then `git stash list --format='%H %gs'` to find its SHA and "
    "`git stash apply <sha>` to restore. Better still, set work aside with a "
    "temporary WIP commit, which is private to your branch.\n\n"
    "Approve only if you are certain no other session is active."
)


def ask(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))


def in_main_checkout(cwd: str) -> bool:
    """True in the shared checkout, False inside a linked worktree.

    `--git-dir` is `<repo>/.git` in the main checkout and
    `<repo>/.git/worktrees/<name>` in a linked one, while `--git-common-dir` is
    `<repo>/.git` in both. Equal means main checkout. Any git failure returns
    False so the guard stays quiet rather than firing outside a repo.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-dir", "--git-common-dir"],
            cwd=cwd or None, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    lines = out.stdout.split()
    if len(lines) != 2:
        return False
    git_dir, common_dir = (os.path.realpath(os.path.join(cwd or ".", p)) for p in lines)
    return git_dir == common_dir


def unsafe_stash_form(tail: str) -> str | None:
    """The risky `git stash ...` form in this command, or None if it is addressed."""
    try:
        args = [a for a in shlex.split(tail) if not a.startswith("-")]
    except ValueError:
        args = tail.split()
    if not args:
        return "git stash"  # Bare `git stash` — implicit push, unnamed.
    sub = args[0]
    if sub in SAFE_STASH_SUBCOMMANDS:
        return None
    if sub == "push":
        return None if re.search(r"(?:^|\s)(?:-m\b|--message\b)", tail) else "git stash push"
    if sub in {"pop", "save"}:
        return f"git stash {sub}"
    return "git stash"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # Malformed payload: stay out of the way rather than block real work.

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return
    cwd = payload.get("cwd") or os.getcwd()

    stash = STASH.search(command)
    if stash:
        form = unsafe_stash_form(stash.group(1))
        if form:
            ask(STASH_REASON.format(form=form))
            return

    switches = SWITCH.search(command) and not FILE_RESTORE.search(command)
    if (switches or RESET_HARD.search(command)) and in_main_checkout(cwd):
        ask(SWITCH_REASON)


if __name__ == "__main__":
    main()
