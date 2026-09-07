"""PreToolUse guard: keep production dumps off the live dev database.

`backups/` holds real production data. The `prod-snapshot` skill restores it into
a separate `pricemanager_snapshot` database precisely so `price_manager_db` never
holds prod rows and never gets dropped by a stray restore flag. This guard refuses
the two ways that rule gets broken:

  * `pg_restore ... -d price_manager_db` — pours prod data into the dev database.
  * `dropdb price_manager_db` / `DROP DATABASE price_manager_db` — the existing
    `guard_compose_down.py` only catches `docker compose down -v`, so these walk
    straight past it and destroy the same volume's contents.

Like the other guards this is a net, not a gate: read-only `psql -d
price_manager_db -c "SELECT ..."` is untouched, and anything aimed at
`pricemanager_snapshot` or `test_price_manager_db` is none of its business.

**It matches on mention, deliberately.** Any command naming the live database
alongside `pg_restore` or a drop verb is refused, wherever in the line the name
sits — parsing `-d` positionally would let `pg_restore <archive> price_manager_db`
and similar orderings through, and a guard that is narrow about the target is
worse than one that occasionally over-fires. The cost is that talking *about*
these commands trips it too: `grep -r "dropdb price_manager_db"` is denied. Quote
the string differently, or run it yourself.
"""
import json
import re
import sys

LIVE_DB = "price_manager_db"

# \b keeps `test_price_manager_db` out of this: the char before `price` is `_`,
# which is a word character, so no boundary matches there.
NAMES_LIVE_DB = re.compile(rf"\b{LIVE_DB}\b")

RESTORES = re.compile(r"\bpg_restore\b")
DROPS = re.compile(r"\bdropdb\b|\bDROP\s+DATABASE\b", re.IGNORECASE)

RESTORE_REASON = (
    f"Blocked: this restores a production dump into `{LIVE_DB}`, the live dev database. "
    "Restore into a separate database instead — `createdb -U priceuser pricemanager_snapshot`, "
    "then `pg_restore ... -d pricemanager_snapshot`. See the `prod-snapshot` skill. "
    "If you genuinely mean to overwrite the dev database, run it yourself."
)

DROP_REASON = (
    f"Blocked: this drops `{LIVE_DB}`, the live dev database. Snapshot work belongs in "
    "`pricemanager_snapshot`, which is safe to drop. See the `prod-snapshot` skill. "
    "If you genuinely mean to drop the dev database, run it yourself."
)


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main() -> None:
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except (json.JSONDecodeError, ValueError):
        return  # Malformed payload: stay out of the way rather than block real work.

    if not NAMES_LIVE_DB.search(command):
        return

    if RESTORES.search(command):
        deny(RESTORE_REASON)
    elif DROPS.search(command):
        deny(DROP_REASON)


if __name__ == "__main__":
    main()
