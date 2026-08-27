import os
from django.core.management.base import BaseCommand, CommandError
from import_export.formats.base_formats import CSV, XLSX
from pim_api import Download

from main_product_manager.pim_client import site
from main_product_manager.resources import MainProductPimImportResource


def _detect_format(file_name: str):
    ext = os.path.splitext(file_name)[1].lower()
    if ext == '.xlsx':
        return XLSX()
    if ext == '.csv':
        return CSV()
    return None


class Command(BaseCommand):
    help = (
        "Импортирует pim_id и категорию в MainProduct из PIM-выгрузки. "
        "Ожидаемые колонки: PriceManagerId, ID, Categories."
    )

    def add_arguments(self, parser):
        parser.add_argument('file_name', help='Имя файла в PIM (например: export.xlsx)')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Только проверить без сохранения',
        )

    def handle(self, *args, **options):
        file_name = options['file_name']

        fmt = _detect_format(file_name)
        if fmt is None:
            raise CommandError(
                f'Неподдерживаемый формат: {file_name}. Используйте .xlsx или .csv'
            )

        self.stdout.write(f'Загрузка файла из PIM: {file_name}')
        try:
            data = site.download(Download(file_name=file_name))
        except Exception as exc:
            raise CommandError(f'Ошибка загрузки файла: {exc}')

        dataset = fmt.create_dataset(data)
        self.stdout.write(f'Строк в файле: {len(dataset)}')

        resource = MainProductPimImportResource()
        result = resource.import_data(dataset, dry_run=options['dry_run'], raise_errors=False)

        if result.has_errors():
            self.stdout.write(self.style.ERROR('Ошибки при импорте:'))
            for row_num, errors in result.row_errors():
                for error in errors:
                    self.stdout.write(self.style.ERROR(f'  Строка {row_num}: {error.error}'))
        else:
            totals = result.totals
            label = 'Тест' if options['dry_run'] else 'Готово'
            self.stdout.write(self.style.SUCCESS(
                f'{label}: новых={totals.get("new", 0)}, '
                f'обновлено={totals.get("update", 0)}, '
                f'пропущено={totals.get("skip", 0)}, '
                f'ошибок={totals.get("error", 0)}'
            ))
