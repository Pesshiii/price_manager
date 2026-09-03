"""Durable capture + retrieval for the Telegram group bot.

The Telegram Bot API exposes neither message history nor search: the bot only
ever sees a message at the instant it arrives. Anything a later summary needs
must therefore be written down *now*. This module is that write-down step, and
the only reader the summary path is allowed to use.

State (all gitignored, under .claude/telegram-bot/state/):
  feedback.jsonl     append-only log of every inbound group message
  actions.jsonl      append-only audit of every GitHub mutation the bot made
  promoted.jsonl     message ids already turned into (or dismissed for) an issue
  last_summary.json  watermark so the next digest continues where the last ended

Appends are idempotent on (chat_id, message_id), so the hook path and the
model-invoked path can both fire for the same message without double-logging.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE = Path(os.environ.get("TG_BOT_STATE") or Path(__file__).resolve().parent / "state")
FEEDBACK = STATE / "feedback.jsonl"
ACTIONS = STATE / "actions.jsonl"
PROMOTED = STATE / "promoted.jsonl"
WATERMARK = STATE / "last_summary.json"

# Attributes Claude Code renders on an inbound channel notification.
CHANNEL_RE = re.compile(r"<channel\s+([^>]*?)>(.*?)</channel>", re.DOTALL)
CHANNEL_OPEN_RE = re.compile(r"<channel\s+([^>]*?)/?>")
ATTR_RE = re.compile(r'([a-z_]+)="([^"]*)"')


def _read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append(path, obj):
    STATE.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_stdin():
    """Decode stdin as UTF-8 regardless of the Windows console codepage.

    json.load(sys.stdin) picks up the locale encoding here (cp1251), which turns
    Russian input into lone surrogates that then blow up on write. Reading the
    raw buffer and decoding explicitly is the only stable route.
    """
    raw = sys.stdin.buffer.read()
    return json.loads(raw.decode("utf-8"))


def _key(entry):
    return "{}:{}".format(entry.get("chat_id"), entry.get("message_id"))


def _seen_keys():
    return {_key(e) for e in _read_jsonl(FEEDBACK)}


def append_entry(entry):
    """Append one inbound message. Returns True if written, False if duplicate."""
    entry = {k: v for k, v in entry.items() if v is not None}
    if not entry.get("text"):
        return False
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
    entry.setdefault("kind", "text")
    if entry.get("message_id") and _key(entry) in _seen_keys():
        return False
    _append(FEEDBACK, entry)
    return True


def cmd_append(args):
    """Convenience path for a single short message. Prefer append-json.

    Cyrillic survives argv fine (verified) -- but real chat text carries quotes,
    newlines and backticks, and shell-quoting those correctly on every call is
    where a capture silently turns into a truncated or dropped message. The JSON
    stdin path has no quoting surface, so that is the one the bot is told to use.
    """
    written = append_entry({
        "chat_id": args.chat,
        "message_id": args.message_id,
        "user": args.user,
        "user_id": args.user_id,
        "ts": args.ts,
        "text": args.text,
        "kind": args.kind,
        "via": "model",
    })
    print("logged" if written else "duplicate")


def cmd_append_json(args):
    payload = _load_stdin()
    entries = payload if isinstance(payload, list) else [payload]
    written = sum(1 for e in entries if append_entry(e))
    print("logged {}/{}".format(written, len(entries)))


def cmd_hook(args):
    """UserPromptSubmit hook: parse inbound <channel> blocks out of the prompt.

    Deterministic belt-and-braces for the model-invoked append. Never blocks and
    never prints on the success path -- stdout from this hook would be injected
    back into the session as context.
    """
    try:
        payload = _load_stdin()
    except Exception:
        return
    prompt = payload.get("prompt") or ""
    if "<channel" not in prompt:
        return
    blocks = CHANNEL_RE.findall(prompt)
    if not blocks:
        blocks = [(m, "") for m in CHANNEL_OPEN_RE.findall(prompt)]
    for attrs, body in blocks:
        meta = dict(ATTR_RE.findall(attrs))
        if meta.get("source") != "telegram":
            continue
        append_entry({
            "chat_id": meta.get("chat_id"),
            "message_id": meta.get("message_id"),
            "user": meta.get("user"),
            "user_id": meta.get("user_id"),
            "ts": meta.get("ts"),
            "text": body.strip(),
            "kind": meta.get("attachment_kind", "text"),
            "image_path": meta.get("image_path"),
            "via": "hook",
        })


def _cutoff(args):
    if getattr(args, "since", None):
        return datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    if getattr(args, "hours", None):
        return datetime.now(timezone.utc) - timedelta(hours=args.hours)
    mark = json.loads(WATERMARK.read_text(encoding="utf-8")) if WATERMARK.exists() else {}
    if mark.get("ts"):
        return datetime.fromisoformat(mark["ts"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _in_window(entry, cutoff, chat):
    if chat and str(entry.get("chat_id")) != str(chat):
        return False
    raw = entry.get("ts")
    if not raw:
        return True
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")) >= cutoff
    except ValueError:
        return True


def cmd_window(args):
    """Everything captured since the cutoff -- the only legitimate summary input."""
    cutoff = _cutoff(args)
    feedback = [e for e in _read_jsonl(FEEDBACK) if _in_window(e, cutoff, args.chat)]
    actions = [a for a in _read_jsonl(ACTIONS) if _in_window(a, cutoff, args.chat)]
    print(json.dumps({
        "cutoff": cutoff.isoformat(),
        "since_date": cutoff.date().isoformat(),
        "message_count": len(feedback),
        "messages": feedback,
        "actions": actions,
    }, ensure_ascii=False, indent=2))


def cmd_pending(args):
    """Captured messages never promoted to an issue and never dismissed."""
    done = {p.get("message_key") for p in _read_jsonl(PROMOTED)}
    cutoff = _cutoff(args)
    rows = [e for e in _read_jsonl(FEEDBACK)
            if _key(e) not in done and _in_window(e, cutoff, args.chat)]
    print(json.dumps({"pending_count": len(rows), "pending": rows},
                     ensure_ascii=False, indent=2))


def cmd_mark_promoted(args):
    for key in args.keys:
        _append(PROMOTED, {
            "message_key": key,
            "issue": args.issue,
            "outcome": args.outcome,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    print("marked {}".format(len(args.keys)))


def cmd_action(args):
    _append(ACTIONS, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": args.action,
        "issue": args.issue,
        "chat_id": args.chat,
        "user": args.user,
        "user_id": args.user_id,
        "note": args.note,
    })
    print("recorded")


def cmd_action_json(args):
    """Audit a GitHub mutation from stdin JSON -- safe for non-ASCII notes."""
    payload = _load_stdin()
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    _append(ACTIONS, payload)
    print("recorded")


def cmd_mark_summary(args):
    STATE.mkdir(parents=True, exist_ok=True)
    WATERMARK.write_text(json.dumps({
        "ts": args.ts or datetime.now(timezone.utc).isoformat(),
        "chat_id": args.chat,
    }, ensure_ascii=False), encoding="utf-8")
    print("watermark set")


def cmd_stats(args):
    feedback = _read_jsonl(FEEDBACK)
    print(json.dumps({
        "state_dir": str(STATE),
        "messages": len(feedback),
        "actions": len(_read_jsonl(ACTIONS)),
        "promoted": len(_read_jsonl(PROMOTED)),
        "first_ts": feedback[0].get("ts") if feedback else None,
        "last_ts": feedback[-1].get("ts") if feedback else None,
        "watermark": json.loads(WATERMARK.read_text(encoding="utf-8")) if WATERMARK.exists() else None,
    }, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description="Telegram bot capture store")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append", help="log one short message via argv (prefer append-json)")
    a.add_argument("--chat", required=True)
    a.add_argument("--message-id")
    a.add_argument("--user")
    a.add_argument("--user-id")
    a.add_argument("--ts")
    a.add_argument("--kind", default="text")
    a.add_argument("--text", required=True)
    a.set_defaults(func=cmd_append)

    aj = sub.add_parser("append-json", help="log entries from stdin JSON (canonical)")
    aj.set_defaults(func=cmd_append_json)

    acj = sub.add_parser("action-json", help="audit a mutation from stdin JSON")
    acj.set_defaults(func=cmd_action_json)

    h = sub.add_parser("hook", help="UserPromptSubmit hook entry point")
    h.set_defaults(func=cmd_hook)

    for name, fn, helptext in (
        ("window", cmd_window, "captured messages + actions since cutoff"),
        ("pending", cmd_pending, "captured messages not yet promoted or dismissed"),
    ):
        w = sub.add_parser(name, help=helptext)
        w.add_argument("--hours", type=int)
        w.add_argument("--since")
        w.add_argument("--chat")
        w.set_defaults(func=fn)

    mp = sub.add_parser("mark-promoted", help="record that messages became an issue")
    mp.add_argument("keys", nargs="+", help="chat_id:message_id keys")
    mp.add_argument("--issue")
    mp.add_argument("--outcome", default="promoted",
                    choices=["promoted", "dismissed", "merged"])
    mp.set_defaults(func=cmd_mark_promoted)

    ac = sub.add_parser("action", help="audit a GitHub mutation")
    ac.add_argument("--action", required=True)
    ac.add_argument("--issue")
    ac.add_argument("--chat")
    ac.add_argument("--user")
    ac.add_argument("--user-id")
    ac.add_argument("--note")
    ac.set_defaults(func=cmd_action)

    ms = sub.add_parser("mark-summary", help="advance the summary watermark")
    ms.add_argument("--ts")
    ms.add_argument("--chat")
    ms.set_defaults(func=cmd_mark_summary)

    st = sub.add_parser("stats", help="state overview")
    st.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
