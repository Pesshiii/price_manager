"""Выгрузка производителей от поставщиков для обогащения PIM (P2-G4).

Запускать на проде ПЕРЕД Phase 2 — Phase 2 удаляет столбец, который эта
команда читает, и после неё выгружать будет нечего. Лучше всего — после
бэкфилла контента из PIM: тогда «без бренда в PIM» значит именно это, а не
«бэкфилл ещё не дошёл». Подробности и причины — в
product/services/manufacturer_export.py и §0.5 брифа.

CSV пишется в stdout, счётчики — в stderr, поэтому перенаправление даёт чистый
файл:

    docker compose exec -T web python manage.py export_manufacturers_for_pim \\
        > manufacturers_for_pim.csv

Или в файл через --output, с BOM, чтобы Excel сразу открыл кириллицу. Путь
внутри контейнера — за пределами /app: /app — это смонтированный репозиторий,
а в файле боевые данные, коммитить их нельзя.

    docker compose exec -T web python manage.py export_manufacturers_for_pim \\
        --output /tmp/manufacturers_for_pim.csv
    docker compose cp web:/tmp/manufacturers_for_pim.csv .
"""

import csv

from django.core.management.base import BaseCommand

from product.services.manufacturer_export import HEADER, build_manufacturer_export


class Command(BaseCommand):
    help = ('Выгружает производителей от поставщиков для товаров без бренда в PIM — '
            'вход для обогащения PIM перед Phase 2.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            help='Файл CSV (UTF-8 с BOM). Без него CSV идёт в stdout.',
        )
        parser.add_argument(
            '--with-disagreements', action='store_true',
            help='Добавить товары, у которых бренд в PIM есть, но ни один поставщик '
                 'его не подтверждает — их бриф просит проверить на стороне PIM.',
        )

    def handle(self, *args, **options):
        result = build_manufacturer_export(include_disagreements=options['with_disagreements'])

        if options['output']:
            with open(options['output'], 'w', newline='', encoding='utf-8-sig') as fh:
                self._write(fh, result.rows)
        else:
            self._write(self.stdout, result.rows)

        self.stderr.write(
            f'Товаров: {result.products}, строк: {len(result.rows)}, '
            f'из них товаров, где поставщики расходятся: {result.products_with_conflict}.'
        )
        self.stderr.write(
            f'Не выгружено товаров с брендом в PIM: {result.skipped_with_pim_brand}.'
        )
        if result.unlinked_supplier_rows:
            self.stderr.write(
                f'Строк поставщиков с производителем, но без товара в каталоге: '
                f'{result.unlinked_supplier_rows} — их производитель тоже уйдёт в Phase 2, '
                f'но обогащать в PIM нечего.'
            )

    @staticmethod
    def _write(stream, rows):
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        writer.writerows(rows)
