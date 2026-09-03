"""PreToolUse guard: refuse `docker compose down -v`.

The postgres_data volume holds real supplier/product data. `down -v` deletes it.
Plain `docker compose down` (containers only) is left alone, and `-v` used as a
verbosity flag on other compose subcommands is not matched.
"""
import json
import re
import sys

REASON = (
    "Blocked: `docker compose down -v` deletes the postgres_data volume, which holds "
    "real supplier/product data in this project. Use `docker compose down` to remove "
    "containers only. If you genuinely need to wipe the database, run it yourself."
)


def main() -> None:
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except (json.JSONDecodeError, ValueError):
        return  # Malformed payload: stay out of the way rather than block real work.

    takes_volumes = re.search(r"(^|\s)(-v|--volumes)(\s|$)", command)
    is_compose_down = re.search(r"compose\b.*\bdown\b", command)
    if takes_volumes and is_compose_down:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REASON,
            }
        }))


if __name__ == "__main__":
    main()
