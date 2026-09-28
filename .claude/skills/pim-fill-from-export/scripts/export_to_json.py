"""Excel/CSV export -> JSON list of row dicts, every value a stripped string or None.

usage: python export_to_json.py <export.xlsx|.csv> <out.json> [--sheet N]

Repeated headers (Satu's Название_Характеристики / Измерение_Характеристики /
Значение_Характеристики triples) are kept apart as `name`, `name.1`, `name.2`, ...
the way pandas numbers them.

Needs pandas + openpyxl. The host python on this machine may lack openpyxl;
the celery_worker image has both:

    docker compose cp <export.xlsx> celery_worker:/tmp/src.xlsx
    docker compose cp export_to_json.py celery_worker:/tmp/
    docker compose exec -T celery_worker python /tmp/export_to_json.py /tmp/src.xlsx /tmp/src.json
    docker compose cp celery_worker:/tmp/src.json <scratchpad>/src.json
"""
import json
import sys

import pandas as pd


def main():
    src, out = sys.argv[1], sys.argv[2]
    sheet = int(sys.argv[sys.argv.index('--sheet') + 1]) if '--sheet' in sys.argv else 0
    if src.lower().endswith('.csv'):
        df = pd.read_csv(src, dtype=str, sep=None, engine='python')
    else:
        df = pd.read_excel(src, dtype=str, sheet_name=sheet)
    rows = []
    for rec in df.to_dict('records'):
        row = {}
        for k, v in rec.items():
            if v is None or (isinstance(v, float) and v != v):
                row[str(k)] = None
            else:
                s = str(v).strip()
                row[str(k)] = s or None
        rows.append(row)
    json.dump(rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'rows {len(rows)} columns {len(df.columns)}')
    for i, c in enumerate(df.columns):
        filled = int(df[c].notna().sum())
        sample = next((str(v)[:60] for v in df[c] if isinstance(v, str) and v.strip()), '')
        print(f'{i}\t{c}\tfilled={filled}\t{sample}')


if __name__ == '__main__':
    main()
