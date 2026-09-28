"""Find the PIM Product of every export row. Read-only.

usage: python match_products.py <rows.json> <out found.json> COL:ATTR [COL:ATTR ...]

Each COL:ATTR pair says "look the value of export column COL up in PIM Product
field ATTR", tried in the order given; the first pair that finds a product wins
for that row. Typical: `Код_товара:number` (Satu), or for a supplier
`okdp:number vendor_code:number barcode:ean`.

Writes found.json = {row_index: {"id", "number", "via"}} and prints
found / missing / ambiguous (a key that hits two PIM products is never guessed:
the row stays unmatched and is listed).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pim import call, where_in  # noqa: E402


def norm(v):
    if v is None:
        return ''
    s = str(v).strip()
    return s[:-2] if s.endswith('.0') and s[:-2].isdigit() else s


def lookup(attr, keys):
    hits = {}
    keys = sorted(keys)
    for i in range(0, len(keys), 80):
        p = {'maxSize': 200, 'select': f'id,number,{attr}' if attr != 'number' else 'id,number'}
        p.update(where_in(attr, keys[i:i + 80]))
        for x in call('GET', 'Product', p)['list']:
            hits.setdefault(norm(x.get(attr)), []).append(x)
        if i and i % 4000 == 0:
            print(f'  {attr}: {i}/{len(keys)}', flush=True)
    return hits


def main():
    rows = json.load(open(sys.argv[1], encoding='utf-8'))
    out = sys.argv[2]
    pairs = [a.split(':', 1) for a in sys.argv[3:]]
    found, ambiguous = {}, []
    for col, attr in pairs:
        pending = {i: norm(r.get(col)) for i, r in enumerate(rows) if str(i) not in found and norm(r.get(col))}
        hits = lookup(attr, set(pending.values()))
        for i, key in pending.items():
            h = hits.get(key, [])
            if len(h) == 1:
                found[str(i)] = {'id': h[0]['id'], 'number': h[0]['number'], 'via': f'{col}->{attr}'}
            elif len(h) > 1:
                ambiguous.append((i, col, key, [x['number'] for x in h]))
        print(f'{col}->{attr}: matched so far {len(found)}', flush=True)
    json.dump(found, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    missing = [i for i in range(len(rows)) if str(i) not in found]
    ids = [v['id'] for v in found.values()]
    print(f'rows {len(rows)} found {len(found)} missing {len(missing)} '
          f'ambiguous-keys {len(ambiguous)} rows-sharing-a-product {len(ids) - len(set(ids))}')
    first = pairs[0][0]
    print('sample missing:', [rows[i].get(first) for i in missing[:15]])
    for a in ambiguous[:10]:
        print('ambiguous:', a)


if __name__ == '__main__':
    main()
