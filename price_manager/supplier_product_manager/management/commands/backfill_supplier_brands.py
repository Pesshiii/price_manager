"""Заполнить бренд поставщика у строк ПП по последнему файлу каждой настройки.

Колонку производителя удалили в Phase 2b, и после возврата бренда (шаг 1
«товар = бренд + артикул») у настроек нет её сопоставления. Команда находит
столбец бренда в последнем файле, сопоставляет его и пишет строкам только
бренд — цены и остатки не трогаются (supplier_product_manager.functions.backfill_brands).

    manage.py backfill_supplier_brands --dry-run
    manage.py backfill_supplier_brands --supplier 12 --supplier 40
"""
from django.core.management.base import BaseCommand

from supplier_product_manager.functions import backfill_brands
from supplier_product_manager.models import Setting

STATUS_LABELS = {
    'filled': 'заполнено',
    'no_file': 'нет файла',
    'no_column': 'нет столбца',
    'error': 'ошибка',
}


class Command(BaseCommand):
    help = 'Бренд поставщика по последнему файлу каждой настройки, без загрузки цен и остатков'

    def add_arguments(self, parser):
        parser.add_argument('--setting', type=int, action='append', default=[], help='pk настройки (можно несколько)')
        parser.add_argument('--supplier', type=int, action='append', default=[], help='pk поставщика (можно несколько)')
        parser.add_argument('--dry-run', action='store_true', help='Ничего не записывать, только отчёт')

    def handle(self, *args, setting, supplier, dry_run, **options):
        settings = Setting.objects.select_related('supplier').order_by('supplier__name', 'name')
        if setting:
            settings = settings.filter(pk__in=setting)
        if supplier:
            settings = settings.filter(supplier_id__in=supplier)

        totals = {status: 0 for status in STATUS_LABELS}
        rows = 0
        for item in settings:
            result = backfill_brands(item, dry_run=dry_run)
            totals[result.status] += 1
            rows += result.rows
            column = f' столбец «{result.column}»{" (найден сейчас)" if result.detected else ""}' if result.column else ''
            detail = f', строк {result.rows}' if result.status == 'filled' else f': {result.message}'
            self.stdout.write(f'{item.supplier.name} — {item.name} [pk {item.pk}]: '
                              f'{STATUS_LABELS[result.status]}{column}{detail}')

        summary = ', '.join(f'{STATUS_LABELS[status]} {count}' for status, count in totals.items())
        prefix = 'Проверка (ничего не записано)' if dry_run else 'Готово'
        self.stdout.write(self.style.SUCCESS(f'{prefix}: настроек {sum(totals.values())} — {summary}; строк с брендом {rows}'))
