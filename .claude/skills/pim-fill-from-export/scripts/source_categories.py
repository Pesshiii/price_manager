"""The export's own category tree in PIM: a `<Src>Category` Hierarchy entity,
its nodes, and each node's `category` link to our Category.

The instance already has five such entities, all the same shape
(SatuCategory, TiradoCategory, MKSCategory, OtvertkaCategory, VICategory):
Hierarchy; name, code (the source's own category id), description, parents;
`category` -> Category, whose reverse side is Category.<src>Categories.
Products are NOT linked to these trees; the tree is mapped to Category instead.

Every command is a dry run that prints / writes a plan. Add --apply to write.

  schema SRC [--label "Ecogr"]            ensure <SRC>Category exists with code + category link
  tree   SRC rows.json --levels ID1:NAME1,ID2:NAME2,...  create missing nodes top-down
  tree   SRC rows.json --leaf ID_COL      (tree already in PIM) only report unknown leaf codes
  map    SRC rows.json found.json (--levels ...|--leaf ID_COL) [--min-share 0.8] [--min-products 3] [--overwrite]
         propose node -> Category from the categories the node's products already have in PIM

A level with an empty id but a name is keyed by its path of names instead.
State lives next to rows.json: <SRC>_tree_ids.json, <SRC>_map.csv.
"""
import argparse
import collections
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pim import call, get_all, metadata, where_in  # noqa: E402


def entity_of(src):
    return src if src.endswith('Category') else f'{src}Category'


def foreign_code(entity):
    base = entity[:-len('Category')]
    return base[0].lower() + base[1:] + 'Categories'


# --- schema ----------------------------------------------------------------

def cmd_schema(a):
    ent = entity_of(a.src)
    md = metadata()
    plan = []
    if ent not in md['scopes']:
        label = a.label or ent[:-len('Category')]
        plan.append(('Entity', {'code': ent, 'name': f'Категория {label}', 'namePlural': f'Категории {label}',
                                'type': 'Hierarchy'}))
        fields = {}
    else:
        if md['scopes'][ent].get('type') != 'Hierarchy':
            sys.exit(f'{ent} exists but is {md["scopes"][ent].get("type")}, not Hierarchy — stop and ask.')
        fields = md['entityDefs'][ent]['fields']
    if 'code' not in fields:
        plan.append(('EntityField', {'entityId': ent, 'code': 'code', 'name': 'Код', 'type': 'varchar'}))
    if 'category' not in fields:
        plan.append(('EntityField', {'entityId': ent, 'code': 'category', 'name': 'Категория', 'type': 'link',
                                     'foreignEntityId': 'Category', 'foreignCode': foreign_code(ent)}))
    if not plan:
        print(f'{ent}: exists, Hierarchy, has code + category. Nothing to do.')
        return
    for scope, body in plan:
        print('PLAN POST', scope, json.dumps(body, ensure_ascii=False))
    if not a.apply:
        print('dry run — rerun with --apply after the user agreed')
        return
    for scope, body in plan:
        r = call('POST', scope, body=body)
        print('created', scope, (r or {}).get('id'))
    md = metadata()
    f = md['entityDefs'].get(ent, {}).get('fields', {})
    cf = md['entityDefs']['Category']['fields'].get(foreign_code(ent))
    ok = md['scopes'].get(ent, {}).get('type') == 'Hierarchy' and 'code' in f and 'category' in f and cf
    print('verify:', 'OK' if ok else f'MISMATCH scope={md["scopes"].get(ent)} fields={sorted(f)} Category.{foreign_code(ent)}={cf}')


# --- tree ------------------------------------------------------------------

def parse_levels(spec):
    return [tuple(x.split(':', 1)) for x in spec.split(',')]


def row_path(row, levels):
    """[(code, name), ...] root first; code falls back to the path of names."""
    path, names = [], []
    for id_col, name_col in levels:
        name = (row.get(name_col) or '').strip()
        code = (row.get(id_col) or '').strip() if id_col else ''
        if code.endswith('.0') and code[:-2].isdigit():
            code = code[:-2]
        if not name and not code:
            break
        names.append(name or code)
        path.append((code or ' > '.join(names), name or code))
    return path


def norm_name(s):
    return ' '.join((s or '').lower().replace('ё', 'е').replace(',', ' ').split())


def existing_codes(ent, apply=False):
    if ent not in metadata()['scopes']:
        if apply:
            sys.exit(f'{ent} does not exist in PIM — run `schema` first.')
        print(f'{ent} does not exist yet (run `schema`); planning against an empty tree')
        return {}
    return {x.get('code'): x['id'] for x in get_all(ent, select='id,name,code') if x.get('code')}


def cmd_tree(a):
    ent = entity_of(a.src)
    rows = json.load(open(a.rows, encoding='utf-8'))
    have = existing_codes(ent, a.apply)
    print(f'{ent}: {len(have)} nodes with a code in PIM')
    if a.leaf:
        leaves = collections.Counter((r.get(a.leaf) or '').strip() for r in rows)
        leaves.pop('', None)
        unknown = {c: n for c, n in leaves.items() if c not in have}
        print(f'leaf codes in export {len(leaves)}, unknown to PIM {len(unknown)} '
              f'({sum(unknown.values())} rows)', list(unknown.items())[:20])
        return
    levels = parse_levels(a.levels)
    nodes = {}  # code -> (name, parent_code)
    for r in rows:
        parent = None
        for code, name in row_path(r, levels):
            prev = nodes.setdefault(code, (name, parent))
            if prev[1] != parent:
                print(f'WARN {code!r} has two parents: {prev[1]!r} and {parent!r} — first kept')
            parent = code
    new = [c for c in nodes if c not in have]
    depth = lambda c: 0 if nodes[c][1] is None else 1 + depth(nodes[c][1])  # noqa: E731
    new.sort(key=depth)
    print(f'tree in export: {len(nodes)} nodes, missing in PIM {len(new)}')
    for c in new[:25]:
        print('  PLAN +', '  ' * depth(c) + nodes[c][0], f'[{c}]')
    if not a.apply:
        print('dry run — rerun with --apply after the user agreed')
        return
    state = Path(a.rows).with_name(f'{a.src}_tree_ids.json')
    ids = dict(have)
    for n, c in enumerate(new):
        name, parent = nodes[c]
        body = {'name': name, 'code': c}
        if parent:
            body['parentsIds'] = [ids[parent]]
        ids[c] = call('POST', ent, body=body)['id']
        if n % 200 == 0:
            json.dump(ids, open(state, 'w', encoding='utf-8'), ensure_ascii=False)
            print(f'  {n}/{len(new)}', flush=True)
    json.dump(ids, open(state, 'w', encoding='utf-8'), ensure_ascii=False)
    print('created', len(new), '->', state)


# --- map -------------------------------------------------------------------

def cmd_map(a):
    ent = entity_of(a.src)
    rows = json.load(open(a.rows, encoding='utf-8'))
    found = json.load(open(a.found, encoding='utf-8'))
    levels = parse_levels(a.levels) if a.levels else None
    products = collections.defaultdict(set)  # leaf code -> PIM product ids
    labels = {}
    for i, r in enumerate(rows):
        if str(i) not in found:
            continue
        if levels:
            path = row_path(r, levels)
            if not path:
                continue
            code = path[-1][0]
            labels[code] = ' > '.join(n for _, n in path)
        else:
            code = (r.get(a.leaf) or '').strip()
            if not code:
                continue
        products[code].add(found[str(i)]['id'])

    pids = sorted({p for s in products.values() for p in s})
    cats_of = collections.defaultdict(set)
    for i in range(0, len(pids), 80):
        p = {'maxSize': 1000, 'select': 'productId,categoryId'}
        p.update(where_in('productId', pids[i:i + 80]))
        for x in call('GET', 'ProductCategory', p)['list']:
            cats_of[x['productId']].add(x['categoryId'])
    cats = get_all('Category', select='id,name,routes,childrenCount')
    cat_name = {c['id']: ' > '.join([n['name'] for r in (c.get('routesNames') or [])[:1] for n in r] + [c['name']])
                for c in cats}
    ancestors = {c['id']: {x for r in (c.get('routes') or []) for x in r.split('|') if x} for c in cats}
    # A product often sits in a category *and* its ancestors, or in a childless catch-all root
    # («Корневая группа», where uncategorised products are parked); either would outvote the
    # specific category. Vote with the most specific real categories only.
    catch_all = {c['id'] for c in cats if not ancestors[c['id']] and not c.get('childrenCount')}
    for pid, cs in cats_of.items():
        above = {a for c in cs for a in ancestors.get(c, ())}
        cats_of[pid] = {c for c in cs if c not in above} - catch_all
    by_name = collections.defaultdict(list)  # fallback when the products have no category yet
    for c in cats:
        by_name[norm_name(c['name'])].append(c['id'])
    if ent in metadata()['scopes']:
        nodes = {x.get('code'): x for x in get_all(ent, select='id,name,code,categoryId,categoryName') if x.get('code')}
    elif a.apply:
        sys.exit(f'{ent} does not exist in PIM — run `schema` and `tree` first.')
    else:
        nodes = {}

    out = Path(a.rows).with_name(f'{a.src}_map.csv')
    w = csv.writer(open(out, 'w', encoding='utf-8-sig', newline=''), delimiter=';')
    w.writerow(['Код', 'Категория источника', 'Товаров', 'С категорией в PIM', 'Предлагаемая Category', 'Доля',
                'Вторая по частоте', 'Сейчас в PIM', 'Действие'])
    todo, stats = [], collections.Counter()
    for code, ps in sorted(products.items(), key=lambda kv: -len(kv[1])):
        node = nodes.get(code)
        votes = collections.Counter(c for p in ps for c in cats_of.get(p, ()))
        with_cat = sum(1 for p in ps if cats_of.get(p))
        best = votes.most_common(2)
        top, share = (best[0][0], best[0][1] / with_cat) if best else (None, 0)
        second = f'{cat_name.get(best[1][0], best[1][0])} ({best[1][1]})' if len(best) > 1 else ''
        current = node and node.get('categoryId')
        leaf_name = (labels.get(code) or (node or {}).get('name', '')).split(' > ')[-1]
        same_name = by_name.get(norm_name(leaf_name), [])
        if not top and len(same_name) == 1:
            top, share = same_name[0], None
        if not node:
            action = 'нет узла в PIM — сначала tree'
        elif not top:
            action = 'у товаров нет категорий — вручную'
        elif share is None:
            if current and not a.overwrite:
                action = 'уже задано' if current == top else 'уже задано иначе — не трогаю'
            elif a.by_name:
                action = 'записать (по названию)'
                todo.append((node['id'], top))
            else:
                action = 'по названию — проверить'
        elif current and not a.overwrite:
            action = 'уже задано' if current == top else 'уже задано иначе — не трогаю'
        elif share >= a.min_share and with_cat >= a.min_products:
            action = 'записать'
            todo.append((node['id'], top))
        else:
            action = 'неуверенно — вручную'
        stats[action] += 1
        w.writerow([code, labels.get(code) or (node or {}).get('name', ''), len(ps), with_cat,
                    cat_name.get(top, top or ''), 'по названию' if share is None else f'{share:.0%}', second,
                    (node or {}).get('categoryName') or '', action])
    print(dict(stats), '->', out)
    if not a.apply:
        print('dry run — rerun with --apply after the user reviewed the CSV')
        return
    for n, (nid, cid) in enumerate(todo):
        call('PATCH', f'{ent}/{nid}', body={'categoryId': cid})
        if n % 200 == 0:
            print(f'  {n}/{len(todo)}', flush=True)
    print('linked', len(todo))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('schema'); s.add_argument('src'); s.add_argument('--label')
    t = sub.add_parser('tree'); t.add_argument('src'); t.add_argument('rows')
    m = sub.add_parser('map'); m.add_argument('src'); m.add_argument('rows'); m.add_argument('found')
    m.add_argument('--min-share', type=float, default=0.8); m.add_argument('--min-products', type=int, default=3)
    m.add_argument('--overwrite', action='store_true')
    m.add_argument('--by-name', action='store_true', help='also write the unique same-name matches')
    for p in (t, m):
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument('--levels'); g.add_argument('--leaf')
    for p in (s, t, m):
        p.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    {'schema': cmd_schema, 'tree': cmd_tree, 'map': cmd_map}[a.cmd](a)


if __name__ == '__main__':
    main()
