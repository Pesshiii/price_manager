"""One-shot bulk embedder for the existing product catalog.

Run synchronously in-process (no Celery hop) so a fresh install can be
indexed before the beat scheduler ever gets a chance to fire. Each batch is
its own transaction-less ``bulk_update`` — failure in one batch logs and
continues, keeping a long backfill resumable.

Examples::

    python manage.py embed_products             # all empty rows
    python manage.py embed_products --all       # re-embed every product
    python manage.py embed_products --batch 32 --limit 1000
    python manage.py embed_products --sku ABC-1 --sku ABC-2
"""
from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from product.models import Product
from product.services.embeddings import EmbeddingServiceError
from product.tasks import _embed_and_save


class Command(BaseCommand):
    help = 'Заполнить эмбеддинги для продуктов (по умолчанию только пустые).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Переэмбеддить все продукты, а не только без вектора.',
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=settings.EMBED_BACKFILL_BATCH_SIZE,
            help='Размер батча (по умолчанию EMBED_BACKFILL_BATCH_SIZE).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Максимальное число обработанных продуктов (для smoke-теста).',
        )
        parser.add_argument(
            '--sku',
            action='append',
            default=[],
            help='Обработать только указанные SKU (можно повторять).',
        )

    def handle(self, *args, **opts):
        batch = max(1, opts['batch'])
        limit = opts['limit']
        skus = opts['sku']

        qs = Product.objects.all().order_by('pk')
        if skus:
            qs = qs.filter(sku__in=skus)
        elif not opts['all']:
            qs = qs.filter(embedding__isnull=True)
        qs = qs.select_related('brand', 'category')

        total = qs.count()
        if limit is not None:
            total = min(total, limit)
        if not total:
            self.stdout.write('Нечего эмбеддить.')
            return

        self.stdout.write(f'Эмбеддим {total} продуктов, батч={batch}.')

        processed = 0
        updated = 0
        started = time.monotonic()
        for offset in range(0, total, batch):
            chunk = list(qs[offset:offset + batch])
            if not chunk:
                break
            try:
                written = _embed_and_save(chunk)
            except EmbeddingServiceError as exc:
                raise CommandError(f'Embedder недоступен: {exc}') from exc
            updated += written
            processed += len(chunk)
            elapsed = time.monotonic() - started
            rate = processed / elapsed if elapsed else 0
            self.stdout.write(
                f'  [{processed}/{total}] обновлено: {updated}, {rate:.1f} prod/s'
            )

        self.stdout.write(self.style.SUCCESS(
            f'Готово: обработано {processed}, обновлено {updated}.'
        ))
