from django.core.management.base import BaseCommand
from main_product_manager.models import MainProduct
from main_product_manager.resources import MainProductResource
from django.core.files.storage import default_storage
from import_export.formats.base_formats import XLSX
from django.core.files.base import ContentFile

class Command(BaseCommand):
    help = "Вызовите эту команду чтобы создать выгрузку главного прайса"

    def handle(self, *args, **options)->None:
        queryset = MainProduct.objects.all()
        resourse = MainProductResource()
        self.stdout.write(self.style.SUCCESS(f'Запуск выгрузки {queryset.count()} товаров'))
        dataset = resourse.export(queryset)
        self.stdout.write(self.style.SUCCESS(f'Датасет готов выгружаем'))
        format_instance = XLSX()
        file_ext = "xlsx"
        exported_data = format_instance.export_data(dataset)
        self.stdout.write(self.style.SUCCESS(f'Выгрузка завершена сохраняем'))
        filename = f'exports/main_product_export.{file_ext}'
        content = ContentFile(exported_data)
        actual_filename = default_storage.save(filename, content)
        self.stdout.write(self.style.SUCCESS(f'Все готово. Путь к файлу: {default_storage.path(actual_filename)}'))