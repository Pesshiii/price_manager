"""PreToolUse guard: make an edit to the retiring API-first stack a conscious choice.

`CLAUDE.md` is unambiguous — `pricing`, `supplier`, `supplier_feed` and
`dataframe` are being retired and take no new features. That rule is currently
enforced by prose alone, which works on a person who has read the file and not
at all on an unattended agent that grepped for a symbol and landed in
`supplier/` instead of `supplier_manager/`. Those two names are one keystroke
apart and confusing them is the single most likely way new code ends up in a
dead app.

So this asks rather than blocks. Bug fixes, test removal and explicitly
requested work in these apps are all legitimate; a new model or route is not,
and a hook cannot tell them apart. Asking puts the judgement back where it
belongs while still catching the accident.

Two deliberate exclusions:

- **`product` is not gated.** It is being actively recreated as a PIM-linked
  mirror and reconnected to the legacy stack, so edits there are normal work.
  Gating it would fire constantly and train the reflex to approve without
  reading, which would cost more than it saves. `product-keeper` owns that line.
- **Only `Edit`/`Write` are matched.** A file rewritten through `Bash` (`sed -i`,
  a heredoc) does not pass through here. Closing that would mean parsing
  arbitrary shell, which is a worse trade than the gap.

Both failure modes are fail-open, by choice: an unreadable payload or a path
that does not resolve under the repo root stays silent rather than blocking real
work. One consequence worth knowing — a *relative* `file_path` is resolved
against the process cwd, so it only classifies correctly while that cwd is the
repo root. Claude Code passes absolute paths, so this is latent, not live.
"""
import json
import sys
from pathlib import Path

# .claude/hooks/guard_retiring_stack.py -> repo root holding docker-compose.yml
REPO_ROOT = Path(__file__).resolve().parents[2]

# The retiring API-first apps, minus `product` -- see the module docstring.
RETIRING = {"pricing", "supplier", "supplier_feed", "dataframe"}

REASON = (
    "`price_manager/{app}/` belongs to the retiring API-first stack. CLAUDE.md: "
    '"The API-driven stack is being retired. Do not build new features here." '
    "The live equivalent is usually a differently-named app -- `supplier` is "
    "retiring, `supplier_manager` is the one being built on.\n\n"
    "Approve this only for a bug fix, a test removal, or work that was asked "
    "for by name. Do not approve a new model, route, serializer or feature. "
    "Deleting one of these apps or its `/api/` route needs its own "
    "confirmation that no external consumer exists -- CLAUDE.md calls that an "
    "open question. Ask `retiring-stack-keeper` if the line is unclear."
)


def retiring_app(file_path: str) -> str | None:
    """The retiring app this path sits in, or None.

    Layout is <repo>/price_manager/<app>/..., and the repo directory is itself
    named price_manager, so the check has to run on the path relative to the
    repo root rather than on any bare `price_manager` segment.
    """
    if not file_path:
        return None
    try:
        parts = Path(file_path).resolve().relative_to(REPO_ROOT).parts
    except (ValueError, OSError):
        return None  # Outside the repo, or unresolvable: not ours to police.
    if len(parts) >= 3 and parts[0] == "price_manager" and parts[1] in RETIRING:
        return parts[1]
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # Malformed payload: stay out of the way rather than block real work.

    app = retiring_app((payload.get("tool_input") or {}).get("file_path", ""))
    if not app:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": REASON.format(app=app),
        }
    }))


if __name__ == "__main__":
    main()
