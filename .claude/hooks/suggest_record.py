"""Stop hook: nudge to record app insights after a session touched an app.

Consulting a keeper agent self-triggers off its description; recording does not.
Without a prompt, every `.claude/knowledge/*.md` file stays frozen at whatever it
was seeded with. This closes that loop.

Emits a `systemMessage` only — it never blocks the stop, so there is no risk of a
hook/stop loop. Stays quiet when nothing mapped changed, and nudges at most once
per (session, app-set) pair — the digest in .claude/.record_nudge folds in the
session id, so one session is not nagged repeatedly, but a later session working
in the same app still gets asked.

Limitation: it reads `git diff --name-only HEAD` plus untracked files, so it only
sees *uncommitted* work. A session that commits everything before stopping leaves
nothing for this to detect and will not be nudged.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# .claude/hooks/suggest_record.py -> repo root holding docker-compose.yml
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE = REPO_ROOT / ".claude" / ".record_nudge"

# Django app dir -> the keeper agent that owns its knowledge file.
KEEPERS = {
    "main_product_manager": "main-product-keeper",
    "core": "core-keeper",
    "product": "product-keeper",
    "supplier_product_manager": "supplier-product-keeper",
    "supplier_manager": "supplier-manager-keeper",
    "product_price_manager": "price-rules-keeper",
    "pricing": "retiring-stack-keeper",
    "supplier": "retiring-stack-keeper",
    "supplier_feed": "retiring-stack-keeper",
    "dataframe": "retiring-stack-keeper",
}


def changed_files() -> list[str]:
    """Tracked edits plus untracked additions, relative to the repo root."""
    out = []
    for args in (
        ["diff", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []  # No git, or too slow: never hold up a stop over tooling.
        if proc.returncode == 0:
            out.extend(line for line in proc.stdout.splitlines() if line.strip())
    return out


def touched_apps(paths: list[str]) -> list[str]:
    """Map `price_manager/<app>/...` paths onto the apps that have a keeper."""
    found = set()
    for path in paths:
        parts = path.replace("\\", "/").split("/")
        # Layout is <repo>/price_manager/<app>/..., so the app is the 2nd segment.
        if len(parts) >= 3 and parts[0] == "price_manager" and parts[1] in KEEPERS:
            found.add(parts[1])
    return sorted(found)


def already_nudged(apps: list[str], session_id: str) -> bool:
    """True if this session was already nudged about exactly this set of apps."""
    key = f"{session_id}|{','.join(apps)}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    try:
        if STATE.read_text(encoding="utf-8").strip() == digest:
            return True
    except OSError:
        pass
    try:
        STATE.write_text(digest, encoding="utf-8")
    except OSError:
        pass  # Read-only checkout: nudge every time rather than not at all.
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    if payload.get("stop_hook_active"):
        return

    # The Telegram bot session stops after every group message, including the
    # silent capture-only turns that are most of a busy group. It never edits
    # code, so this nudge can never fire usefully there -- and the two git
    # subprocesses below would run per message. start-bot.ps1 sets the flag.
    if os.environ.get("TG_BOT_SESSION"):
        return

    apps = touched_apps(changed_files())
    if not apps or already_nudged(apps, str(payload.get("session_id", ""))):
        return

    lines = [f"  - {app} -> /record-insight {app}" for app in apps]
    keepers = sorted({KEEPERS[app] for app in apps})
    print(json.dumps({
        "systemMessage": (
            "This session touched "
            + ", ".join(apps)
            + ". If anything non-obvious was learned — a trap, a surprising side "
            "effect, a why-it-is-like-this — record it now so the next session "
            "starts with it:\n"
            + "\n".join(lines)
            + "\n\nKeeper agents: "
            + ", ".join(keepers)
            + ". Nothing to record is a fine answer; skip it."
        )
    }))


if __name__ == "__main__":
    main()
