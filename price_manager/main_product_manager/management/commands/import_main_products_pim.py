import os
from urllib.parse import urlparse
import httpx
from django.core.management.base import BaseCommand, CommandError
from import_export.formats.base_formats import CSV, XLSX
from main_product_manager.resources import MainProductPimImportResource


def _detect_format(name: str):
    ext = os.path.splitext(name)[1].lower().split('?')[0]
    if ext == '.xlsx':
        return XLSX()
    if ext == '.csv':
        return CSV()
    return None


class Command(BaseCommand):
    help = (
        "Импортирует pim_id и категорию в MainProduct из файла PIM-выгрузки. "
        "Принимает локальный путь или URL. "
        "Ожидаемые колонки: PriceManagerId, ID, Categories."
    )

    def add_arguments(self, parser):
        parser.add_argument('source', help='Путь к файлу или URL (CSV или XLSX)')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Только проверить без сохранения',
        )

    def handle(self, *args, **options):
        source = options['source']
        parsed = urlparse(source)
        is_url = parsed.scheme in ('http', 'https')

        if is_url:
            self.stdout.write(f'Загрузка файла: {source}')
            try:
                response = httpx.get(source, follow_redirects=True, timeout=60.0)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CommandError(f'Ошибка загрузки файла: {exc}')
            data = response.content
            # попытаться определить формат из URL или Content-Disposition
            content_disposition = response.headers.get('content-disposition', '')
            filename = source
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[-1].strip().strip('"')
            fmt = _detect_format(filename)
            if fmt is None:
                # по Content-Type
                content_type = response.headers.get('content-type', '')
                if 'spreadsheet' in content_type or 'xlsx' in content_type:
                    fmt = XLSX()
                elif 'csv' in content_type or 'text/' in content_type:
                    fmt = CSV()
                else:
                    raise CommandError(
                        'Не удалось определить формат файла. Добавьте расширение .xlsx или .csv в URL.'
                    )
        else:
            if not os.path.exists(source):
                raise CommandError(f'Файл не найден: {source}')
            fmt = _detect_format(source)
            if fmt is None:
                raise CommandError(
                    f'Неподдерживаемый формат: {source}. Используйте .xlsx или .csv'
                )
            with open(source, 'rb') as fh:
                data = fh.read()

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
