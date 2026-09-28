"""Minimal AtroPIM REST client for the pim-fill-from-export skill.

Reads PIM_HOST / PIM_TOKEN the same way .claude/tools/pim_docs.py does (the
environment, else this checkout's .env, else the main checkout's .env), so it
works from a worktree and from a scratchpad. Import it with:

    sys.path.insert(0, r'<repo>/.claude/skills/pim-fill-from-export/scripts')
    from pim import call, get_all, where_in, HOST
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from pim_docs import dotenv_values  # noqa: E402

_v = dotenv_values()
HOST = re.sub(r'^https?://', '', _v['PIM_HOST']).strip('/')


def call(method, path, params=None, body=None, headers=None):
    """One request. Raises RuntimeError('<METHOD> <path> -> <code>: <body>').

    A 304 on a write means "nothing changed" and is a success for idempotent
    upserts; callers decide (see upsert_values.py).
    """
    url = f'https://{HOST}/api/{path.lstrip("/")}'
    if params:
        url += '?' + urllib.parse.urlencode(params, doseq=True)
    # Cloudflare in front of the PIM rejects urllib's default User-Agent (403 / 1010).
    h = {'Accept': 'application/json', 'Authorization-Token': _v['PIM_TOKEN'],
         'User-Agent': 'price_manager-pim-fill', 'Content-Type': 'application/json'}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, headers=h, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read().decode('utf-8')
            return json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{method} {path} -> {e.code}: {e.read().decode("utf-8", "replace")[:500]}')


def get_all(entity, select=None, where=None, page=200):
    """Every row of a list endpoint. `where` is a dict of where[...] params."""
    out, off = [], 0
    while True:
        p = {'maxSize': page, 'offset': off}
        if select:
            p['select'] = select
        if where:
            p.update(where)
        r = call('GET', entity, p)
        out += r['list']
        off += page
        if off >= r['total'] or not r['list']:
            return out


def where_in(attribute, values, n=0):
    """where[n] params for `attribute IN values` (keep values <= 100 per call)."""
    p = {f'where[{n}][attribute]': attribute, f'where[{n}][type]': 'in'}
    for j, v in enumerate(values):
        p[f'where[{n}][value][{j}]'] = v
    return p


def metadata():
    return call('GET', 'metadata')


def card_url(entity, pid):
    return f'https://{HOST}/#{entity}/view/{pid}'
