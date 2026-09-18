"""Наполняет зеркало (Product/Category/Brand) содержимым PIM оптом.

Для разработки и проверки на настоящих данных. Читает PIM и НИЧЕГО в него не
пишет — в отличие от reindex_pim_ids, который создаёт в PIM записи
PriceManagerProduct. На снимке прода это принципиально: писать в боевой PIM из
дев-стенда нельзя.

Три шага, порядок жёсткий:
  1. дерево категорий из PIM (создаёт, переименовывает, переподвешивает);
  2. товары постранично, сопоставление по number (= MainProduct.sku),
     заодно бренды и связи с категориями;
  3. пересборка search_vector по затронутым строкам.

    docker compose --env-file <путь>/.env exec -e POSTGRES_DB=... web \\
        python manage.py load_pim_mirror --limit 20000
"""

import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from product.models import Product
from product.services.pim_sync import (
    load_products_by_number,
    sync_category_tree_from_pim,
)


class Command(BaseCommand):
    help = 'Наполняет локальное зеркало содержимым PIM (только чтение из PIM).'

    def add_arguments(self, parser):
        parser.add_argument('--page-size', type=int, default=1000)
        parser.add_argument('--limit', type=int, default=None,
                            help='Сколько товаров PIM просмотреть (для быстрой проверки).')
        parser.add_argument('--start-offset', type=int, default=0,
                            help='С какого смещения продолжить прерванный прогон.')
        parser.add_argument('--skip-categories', action='store_true',
                            help='Не трогать дерево категорий.')
        parser.add_argument('--skip-vectors', action='store_true',
                            help='Не пересобирать search_vector.')

    def handle(self, *args, **options):
        if not options['skip_categories']:
            self.stdout.write('Синхронизирую дерево категорий…')
            started = time.monotonic()
            stats = sync_category_tree_from_pim()
            self.stdout.write(self.style.SUCCESS(
                f'  категорий в PIM {stats["total"]}: создано {stats["created"]}, '
                f'переименовано {stats["renamed"]}, переподвешено {stats["reparented"]} '
                f'({time.monotonic() - started:.1f}с)'
            ))

        self.stdout.write('Загружаю товары…')
        started = time.monotonic()

        def progress(scanned, total, matched):
            self.stdout.write(
                f'  просмотрено {scanned}/{total}, сопоставлено {matched} '
                f'({time.monotonic() - started:.0f}с)'
            )

        stats = load_products_by_number(
            page_size=options['page_size'], limit=options['limit'],
            start_offset=options['start_offset'], progress=progress,
        )
        self.stdout.write(self.style.SUCCESS(
            f'  просмотрено {stats["scanned"]} из {stats["pim_total"]}, '
            f'сопоставлено {stats["matched"]}, мимо зеркала {stats["skipped"]} '
            f'({time.monotonic() - started:.1f}с)'
        ))

        if options['skip_vectors']:
            return

        self.stdout.write('Пересобираю search_vector…')
        started = time.monotonic()
        # Только по наполненным строкам: у пустых вектор состоит из одного
        # number, и тратить на них проход незачем.
        queryset = Product.objects.exclude(raw_data={}).exclude(raw_data__isnull=True)
        done = 0
        for product in queryset.iterator(chunk_size=500):
            product.rebuild_search_vector()
            done += 1
            if done % 5000 == 0:
                self.stdout.write(f'  {done} ({time.monotonic() - started:.0f}с)')
        self.stdout.write(self.style.SUCCESS(
            f'  векторов пересобрано {done} ({time.monotonic() - started:.1f}с)'
        ))

        with_content = Product.objects.exclude(Q(raw_data={}) | Q(raw_data__isnull=True)).count()
        self.stdout.write('')
        self.stdout.write(f'Товаров с данными PIM: {with_content} из {Product.objects.count()}')
