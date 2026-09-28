"""Write a prepared plan into PIM products. Resumable, safe to re-run.

usage: python upsert_values.py <plan.json> <ids.json> [--only PID ...] [--threads N]

plan.json = {pim_product_id: {"fields": {field: value, ...},
                              "attrs": {attr_code: [value, unit_code_or_null], ...}}}
ids.json  = {"attr": {attr_code: attribute_id}, "unit": {"<measure>.<unit>": unit_id},
             "attr_measure": {attr_code: measure_code}}

Per product: PATCH Product/{id} with "fields" (description etc.), then
POST Product/{id}/upsertAttributeValues with "attrs" — only the attributes
passed are touched. Progress goes to push.log next to plan.json; a product
already logged `ok` is skipped, so an interrupted run continues where it
stopped. 304 Not Modified counts as ok (nothing changed).

Default is ONE thread (~100 products/min). --threads 4 gave ~390/min on
2026-09-28 without errors, but it loads production PIM: only with the user's
explicit consent.
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pim import call  # noqa: E402


def main():
    plan_path = Path(sys.argv[1])
    plan = json.load(open(plan_path, encoding='utf-8'))
    ids = json.load(open(sys.argv[2], encoding='utf-8'))
    threads = int(sys.argv[sys.argv.index('--threads') + 1]) if '--threads' in sys.argv else 1
    log_path = plan_path.with_name('push.log')

    done = set()
    if log_path.exists():
        for line in open(log_path, encoding='utf-8'):
            p = line.split()
            if len(p) > 1 and p[0] == 'ok':
                done.add(p[1])
    if '--only' in sys.argv:
        i = sys.argv.index('--only') + 1
        todo = [a for a in sys.argv[i:] if not a.startswith('--')]
    else:
        todo = [p for p in sorted(plan) if p not in done]
    print('already', len(done), 'todo', len(todo), flush=True)

    def attr_payload(attrs):
        out = []
        for code, (val, unit) in attrs.items():
            item = {'attributeId': ids['attr'][code], 'value': val}
            if unit:
                item['valueUnitId'] = ids['unit'][f"{ids['attr_measure'][code]}.{unit}"]
            out.append(item)
        return out

    def write(method, path, body):
        try:
            call(method, path, body=body)
        except RuntimeError as e:
            if '-> 304' not in str(e):
                raise

    lock, cnt = threading.Lock(), [0]
    log = open(log_path, 'a', encoding='utf-8')

    def one(pid):
        item = plan[pid]
        res = None
        for attempt in range(3):
            try:
                if item.get('fields'):
                    write('PATCH', f'Product/{pid}', item['fields'])
                if item.get('attrs'):
                    write('POST', f'Product/{pid}/upsertAttributeValues', attr_payload(item['attrs']))
                res = f"ok {pid} {len(item.get('fields', {}))}f {len(item.get('attrs', {}))}a"
                break
            except Exception as e:  # noqa: BLE001 — logged, retried, never swallowed silently
                if attempt == 2:
                    res = f'FAIL {pid} {str(e)[:300]}'
                else:
                    time.sleep(5 * (attempt + 1))
        with lock:
            print(res, file=log, flush=True)
            cnt[0] += 1
            if res.startswith('FAIL'):
                print(res, flush=True)
            if cnt[0] % 1000 == 0:
                print(cnt[0], 'of', len(todo), flush=True)

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    print('FINISHED', cnt[0], flush=True)


if __name__ == '__main__':
    main()
