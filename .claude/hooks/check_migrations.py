"""PostToolUse check: flag model/migration drift right after a models.py edit.

Runs the project's own drift check inside the running web container. Stays silent
unless there is real drift, so it costs nothing on unrelated edits or when the
Docker stack is down.
"""
import json
import subprocess
import sys
from pathlib import Path

# .claude/hooks/check_migrations.py -> repo root holding docker-compose.yml
REPO_ROOT = Path(__file__).resolve().parents[2]


def edited_path(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    return tool_input.get("file_path") or tool_response.get("filePath") or ""


def compose(*args: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    if not edited_path(payload).replace("\\", "/").endswith("models.py"):
        return

    try:
        running = compose("ps", "--status=running", "--format", "{{.Name}}", timeout=20)
        if "price_manager_web" not in running.stdout:
            return  # Stack is down — nothing to check against, and no reason to complain.

        check = compose(
            "exec", "-T", "web",
            "python", "manage.py", "makemigrations", "--check", "--dry-run",
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return  # Docker unavailable or slow: never block an edit over tooling trouble.

    if check.returncode == 0:
        return

    detail = (check.stdout + check.stderr).strip()[-1500:]
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "Model change left migrations out of date (`makemigrations --check` "
                f"exited {check.returncode}). Generate a migration with "
                "`docker compose exec web python manage.py makemigrations <app>` "
                f"before moving on.\n\n{detail}"
            ),
        }
    }))


if __name__ == "__main__":
    main()
