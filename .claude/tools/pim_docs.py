"""AtroCore / AtroPIM documentation and read-only instance metadata, for the
`pim-docs` subagent (.claude/agents/pim-docs.md).

Docs come from the public GitHub mirror of help.atrocore.com
(github.com/atrocore/atrocore, docs/), sparse-cloned per version tag into
~/.cache/atrocore-docs/<ref>/ — verbatim markdown, not a summary of rendered HTML.

The instance side is deliberately narrow: two fixed GET endpoints
(/api/metadata and /openapi.json), nothing else. The token is read from the
environment or the repo's .env and never printed.

    python .claude/tools/pim_docs.py toc [FILTER]
    python .claude/tools/pim_docs.py grep PATTERN [-i] [-C N] [--max N]
    python .claude/tools/pim_docs.py read PAGE [--outline] [--lines A-B]
    python .claude/tools/pim_docs.py diff PAGE [--against master]
    python .claude/tools/pim_docs.py instance version
    python .claude/tools/pim_docs.py instance metadata [DOTTED.PATH] [--keys]
    python .claude/tools/pim_docs.py instance openapi (--list [REGEX] | --path REGEX | --schema NAME)

Every docs command takes --ref (default: DOCS_REF). PAGE is a file path, a
help.atrocore.com URL, or a slug / slug suffix such as `rest-api`.
"""
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The AtroCore version the team's PIM runs. Change it here when the PIM is
# upgraded; `instance version` warns when the two disagree.
DOCS_REF = '2.3.15'

REPO_URL = 'https://github.com/atrocore/atrocore.git'
HELP_SITE = 'https://help.atrocore.com'
CACHE_DIR = Path.home() / '.cache' / 'atrocore-docs'
BRANCH_MAX_AGE = 24 * 3600    # tags are immutable; a branch checkout is re-cloned after this
INSTANCE_MAX_AGE = 3600
PLACEHOLDER_HOSTS = {'', 'pim.invalid'}
OUTPUT_LIMIT = 20000

REPO_ROOT = Path(__file__).resolve().parents[2]


def fail(message):
    print(f'error: {message}', file=sys.stderr)
    sys.exit(1)


# --- docs ------------------------------------------------------------------

def is_tag(ref):
    return re.fullmatch(r'\d+\.\d+\.\d+(-[\w.]+)?', ref) is not None


def docs_root(ref):
    """Checkout of docs/**/*.md at `ref`, cloning on first use."""
    checkout = CACHE_DIR / ref
    stamp = checkout / '.fetched'
    if stamp.exists() and (is_tag(ref) or time.time() - stamp.stat().st_mtime < BRANCH_MAX_AGE):
        return checkout / 'docs'
    if checkout.exists():
        shutil.rmtree(checkout)
    checkout.parent.mkdir(parents=True, exist_ok=True)
    print(f'[cloning atrocore docs at {ref} ...]', file=sys.stderr)
    steps = [
        ['git', 'clone', '-q', '--depth', '1', '--branch', ref, '--filter=blob:none',
         '--no-checkout', REPO_URL, str(checkout)],
        ['git', '-C', str(checkout), 'sparse-checkout', 'set', '--no-cone', '/docs/**/*.md'],
        ['git', '-C', str(checkout), 'checkout', '-q'],
    ]
    for cmd in steps:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            shutil.rmtree(checkout, ignore_errors=True)
            fail(f'{" ".join(cmd[:3])} failed for ref {ref!r}: {result.stderr.strip()}')
    stamp.touch()
    return checkout / 'docs'


def slug_of(rel):
    """docs/10.developer-guide/10.rest-api/index.md -> developer-guide/rest-api.

    Every page is a directory holding one markdown file, whatever it is named
    (index.md, chapter.md, and at least one `idex.md` typo).
    """
    parts = rel.parts[:-1] if len(rel.parts) > 1 else (rel.stem,)
    return '/'.join(re.sub(r'^\d+\.', '', p) for p in parts).lower()


def help_url(ref, slug):
    return f'{HELP_SITE}/{"v" + ref if is_tag(ref) else "latest"}/{slug}'


def title_of(path):
    match = re.search(r'^title:\s*(.+)$', path.read_text(encoding='utf-8')[:500], re.M)
    return match.group(1).strip().strip('\'"') if match else ''


def pages(ref):
    root = docs_root(ref)
    return {slug_of(p.relative_to(root)): p for p in sorted(root.rglob('*.md'))}


def resolve(ref, page):
    """Map a file path, help URL or slug (suffix) to (slug, path)."""
    index = pages(ref)
    root = docs_root(ref)
    candidate = Path(page.replace('\\', '/').removeprefix('docs/'))
    if (root / candidate).is_file():
        path = root / candidate
        return slug_of(path.relative_to(root)), path
    slug = re.sub(r'^https?://[^/]+', '', page).split('#')[0].split('?')[0].strip('/').lower()
    slug = re.sub(r'^(latest|v\d+\.\d+\.\d+)(/docs)?/', '', slug)
    if slug in index:
        return slug, index[slug]
    matches = [s for s in index if s == slug or s.endswith('/' + slug)]
    if len(matches) == 1:
        return matches[0], index[matches[0]]
    if matches:
        fail(f'{page!r} is ambiguous at {ref}:\n  ' + '\n  '.join(matches))
    fail(f'no docs page {page!r} at {ref}. This resolves help.atrocore.com pages only — '
         f'find one with `toc` or `grep`; read repo files with the Read tool.')


def cmd_toc(args):
    for slug, path in pages(args.ref).items():
        title = title_of(path)
        if args.filter and args.filter.lower() not in f'{slug} {title}'.lower():
            continue
        print(f'{slug}  —  {title}')
    print(f'\n[ref {args.ref}; URL = {help_url(args.ref, "<slug>")}]')


def cmd_grep(args):
    pattern = re.compile(args.pattern, re.I if args.ignore_case else 0)
    root = docs_root(args.ref)
    shown = 0
    for slug, path in pages(args.ref).items():
        lines = path.read_text(encoding='utf-8').splitlines()
        hits = [i for i, line in enumerate(lines) if pattern.search(line)]
        if not hits:
            continue
        print(f'== {path.relative_to(root.parent).as_posix()}  {help_url(args.ref, slug)}')
        printed = set()
        for i in hits:
            if shown >= args.max:
                break
            for j in range(max(0, i - args.context), min(len(lines), i + args.context + 1)):
                if j not in printed:
                    printed.add(j)
                    print(f'{j + 1:>5}{":" if j == i else "-"} {lines[j]}')
            shown += 1
        if shown >= args.max:
            print(f'\n[stopped at --max {args.max} matches; narrow the pattern]')
            return
    if not shown:
        print(f'[no match for {args.pattern!r} at {args.ref}]')


def cmd_read(args):
    slug, path = resolve(args.ref, args.page)
    lines = path.read_text(encoding='utf-8').splitlines()
    print(f'# {title_of(path)}\n# file: {path.relative_to(docs_root(args.ref).parent).as_posix()} @ {args.ref}'
          f'\n# url:  {help_url(args.ref, slug)}\n')
    if args.outline:
        for i, line in enumerate(lines):
            if re.match(r'#{1,6} ', line):
                print(f'{i + 1:>5}: {line}')
        return
    start, end = 1, len(lines)
    if args.lines:
        start, _, end = args.lines.partition('-')
        start, end = int(start), int(end or len(lines))
    for i in range(start - 1, min(end, len(lines))):
        print(f'{i + 1:>5}: {lines[i]}')


def cmd_diff(args):
    old_slug, old_path = resolve(args.ref, args.page)
    new_index = pages(args.against)
    if old_slug not in new_index:
        print(f'[{old_slug} does not exist at {args.against} — moved or removed]')
        return
    diff = list(difflib.unified_diff(
        old_path.read_text(encoding='utf-8').splitlines(),
        new_index[old_slug].read_text(encoding='utf-8').splitlines(),
        f'{old_slug} @ {args.ref}', f'{old_slug} @ {args.against}', lineterm='', n=2))
    print('\n'.join(diff) if diff else f'[{old_slug} is identical at {args.ref} and {args.against}]')


# --- instance (read-only) --------------------------------------------------

def dotenv_values():
    """PIM_* from the environment, else from .env — this checkout's, or the main
    checkout's when running from a worktree (a fresh worktree has no .env)."""
    values = {k: os.environ[k] for k in ('PIM_HOST', 'PIM_TOKEN') if os.environ.get(k)}
    if len(values) == 2:
        return values
    candidates = [REPO_ROOT / '.env']
    common = subprocess.run(['git', '-C', str(REPO_ROOT), 'rev-parse', '--git-common-dir'],
                            capture_output=True, text=True).stdout.strip()
    if common:
        common_dir = Path(common) if Path(common).is_absolute() else REPO_ROOT / common
        candidates.append(common_dir.resolve().parent / '.env')
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.strip().partition('=')
            if sep and key.strip() in ('PIM_HOST', 'PIM_TOKEN') and key.strip() not in values:
                values[key.strip()] = value.strip().strip('\'"')
        if len(values) == 2:
            break
    return values


def instance_get(endpoint, refresh=False):
    """GET one of the two whitelisted endpoints, cached for an hour."""
    assert endpoint in ('/api/metadata', '/openapi.json')
    values = dotenv_values()
    host = re.sub(r'^https?://', '', values.get('PIM_HOST', '')).strip('/')
    if host in PLACEHOLDER_HOSTS or not values.get('PIM_TOKEN') or values['PIM_TOKEN'] == 'dummy-token':
        fail('no real PIM configured: PIM_HOST / PIM_TOKEN are unset or placeholders '
             '(looked in the environment and .env).')
    cache = CACHE_DIR / 'instance' / host / (endpoint.strip('/').replace('/', '_') + '.json')
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < INSTANCE_MAX_AGE:
        return json.loads(cache.read_text(encoding='utf-8'))
    # Cloudflare in front of the PIM answers urllib's default `Python-urllib/x.y`
    # User-Agent with 403 / error 1010 before the token is ever checked.
    request = urllib.request.Request(
        f'https://{host}{endpoint}', method='GET',
        headers={'Accept': 'application/json', 'Authorization-Token': values['PIM_TOKEN'],
                 'User-Agent': 'price_manager-pim-docs'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        hint = ' (token rejected)' if exc.code == 401 else ''
        fail(f'GET {endpoint} -> HTTP {exc.code}{hint}')
    except urllib.error.URLError as exc:
        fail(f'GET {endpoint} failed: {exc.reason}')
    data = json.loads(body)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(body, encoding='utf-8')
    return data


def emit(value):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT] + f'\n[... truncated at {OUTPUT_LIMIT} of {len(text)} chars; go deeper or use --keys]'
    print(text)


def cmd_version(args):
    info = instance_get('/openapi.json', args.refresh).get('info', {})
    version = info.get('version', '?')
    print(f'instance: {version}\ndocs pinned: {DOCS_REF}')
    if version != DOCS_REF:
        print(f'MISMATCH — the instance runs {version}, the docs are pinned to {DOCS_REF}. '
              f'Pass --ref {version} or update DOCS_REF in {Path(__file__).name}.')


def cmd_metadata(args):
    node = instance_get('/api/metadata', args.refresh)
    walked = []
    for key in filter(None, (args.path or '').split('.')):
        if not isinstance(node, dict) or key not in node:
            options = sorted(node)[:80] if isinstance(node, dict) else []
            fail(f'no key {key!r} under {".".join(walked) or "<root>"}. Keys: {", ".join(options)}')
        node = node[key]
        walked.append(key)
    if args.keys and isinstance(node, dict):
        for key, value in node.items():
            size = f'{len(value)} keys' if isinstance(value, dict) else json.dumps(value, ensure_ascii=False)[:80]
            print(f'{key}: {size}')
    else:
        emit(node)


def cmd_openapi(args):
    spec = instance_get('/openapi.json', args.refresh)
    if args.schema:
        schemas = spec.get('components', {}).get('schemas', {})
        if args.schema not in schemas:
            near = [s for s in schemas if args.schema.lower() in s.lower()][:40]
            fail(f'no schema {args.schema!r}. Similar: {", ".join(near) or "none"}')
        emit(schemas[args.schema])
    elif args.path:
        emit({p: v for p, v in spec.get('paths', {}).items() if re.search(args.path, p)})
    else:
        pattern = re.compile(args.list or '.')
        for path, ops in spec.get('paths', {}).items():
            if pattern.search(path):
                print(f'{path}  [{", ".join(m.upper() for m in ops)}]')


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    def docs_command(name, func, **kwargs):
        p = sub.add_parser(name, **kwargs)
        p.add_argument('--ref', default=DOCS_REF, help=f'docs version tag or branch (default {DOCS_REF})')
        p.set_defaults(func=func)
        return p

    p = docs_command('toc', cmd_toc, help='list pages')
    p.add_argument('filter', nargs='?')
    p = docs_command('grep', cmd_grep, help='regex search across every page')
    p.add_argument('pattern')
    p.add_argument('-i', '--ignore-case', action='store_true')
    p.add_argument('-C', '--context', type=int, default=0)
    p.add_argument('--max', type=int, default=60)
    p = docs_command('read', cmd_read, help='print a page with line numbers')
    p.add_argument('page')
    p.add_argument('--outline', action='store_true', help='headings only')
    p.add_argument('--lines', help='A-B')
    p = docs_command('diff', cmd_diff, help='how a page changed between --ref and --against')
    p.add_argument('page')
    p.add_argument('--against', default='master')

    instance = sub.add_parser('instance', help='read-only GETs against the team PIM').add_subparsers(
        dest='what', required=True)
    p = instance.add_parser('version')
    p.set_defaults(func=cmd_version)
    p = instance.add_parser('metadata')
    p.add_argument('path', nargs='?', help='dotted path, e.g. entityDefs.Product.fields.number')
    p.add_argument('--keys', action='store_true', help='list keys at this node instead of dumping it')
    p.set_defaults(func=cmd_metadata)
    p = instance.add_parser('openapi')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', nargs='?', const='.', metavar='REGEX', help='list API paths')
    group.add_argument('--path', metavar='REGEX', help='dump matching path objects')
    group.add_argument('--schema', metavar='NAME', help='dump one component schema')
    p.set_defaults(func=cmd_openapi)
    for p in instance.choices.values():
        p.add_argument('--refresh', action='store_true', help='bypass the one-hour cache')

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
