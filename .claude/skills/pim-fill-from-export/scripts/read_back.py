"""Compare what PIM now holds with the plan, for a handful of products. Read-only.

usage: python read_back.py <plan.json> <ids.json> PID [PID ...]

Prints every mismatch and a card link per product, so the pilot can be shown to
the user. For attributes with a unit it also prints `<code>AllUnits` from the
flattened record: that is where a wrong unit multiplier shows up (60 g must read
0.06 kg, not 60000 kg).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pim import call, card_url  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    plan = json.load(open(sys.argv[1], encoding='utf-8'))
    ids = json.load(open(sys.argv[2], encoding='utf-8'))
    code_of = {v: k for k, v in ids['attr'].items()}
    bad = 0
    for pid in sys.argv[3:]:
        item = plan[pid]
        rec = call('GET', f'Product/{pid}')
        for f, v in item.get('fields', {}).items():
            if rec.get(f) != v:
                bad += 1
                print('MISMATCH', pid, f, repr(rec.get(f))[:80], '!=', repr(v)[:80])
        got = {code_of.get(x['attributeId']): x for x in call('GET', f'Product/{pid}/attributeValues') or []}
        for code, (val, unit) in item.get('attrs', {}).items():
            x = got.get(code)
            ok = x is not None and x.get('value') == val
            if unit and x is not None:
                ok = ok and x.get('valueUnitId') == ids['unit'][f"{ids['attr_measure'][code]}.{unit}"]
            if not ok:
                bad += 1
                print('MISMATCH', pid, code, x and x.get('value'), x and x.get('valueUnitId'), '!=', val, unit)
        flat = call('GET', f'Product/{pid}', headers={'Flatten-Attributes': 'true'})
        units = {k: v for k, v in flat.items() if k.endswith('AllUnits') and v}
        print(card_url('Product', pid), {k: v for k, v in list(units.items())[:3]})
    print('mismatches', bad)


if __name__ == '__main__':
    main()
