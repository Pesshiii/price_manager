from django.core.management.base import BaseCommand
from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from main_product_manager.pim_api import site, UpsertAsync, Job, EntityList, Where
from time import sleep

class Command(BaseCommand):
    help = "Вызовите эту команду чтобы насытить продукты информацией из API."

    def handle(self, *args, **options)->None:
        suppliers = Supplier.objects.all()
        products = MainProduct.objects.all().select_related('supplier')
        self.stdout.write(self.style.SUCCESS(f'Начало выполнения задачи. Число поставщиков: {suppliers.count()}, товаров: {products.count()}'))
        s_payload = []
        count = 0
        for supplier in suppliers:
            s_payload.append({'entity':'Account', 'payload':{'name':supplier.name, 'role': 'supplier'}})
            count += 1
            if count%200==0:
                s_id = site.get(UpsertAsync(payload=s_payload))['jobId']
                self.stdout.write(msg=f'Задача {s_id}. Кол-во поставщиков {len(s_payload)}')
                s_payload = []
        if not count%200==0:
                s_id = site.get(UpsertAsync(payload=s_payload))['jobId']
                self.stdout.write(msg=f'Задача {s_id}. Кол-во поставщиков {len(s_payload)}')
        count = 0
        mp_payload = []
        def _get_supplier_id(name: str)->str:
            return site.get(EntityList(name='Account', where=[Where(attribute='name', type='like', value=name)]))['list'][0]['id']
        for product in products:
            mp_payload.append({'entity':'Product', 'payload':{'name':product.name, 'mpn': product.article, 'number': product.article, 'defaultSupplierId':_get_supplier_id(product.supplier.name)}})
            count += 1
            if count%200==0:
                mp_id = site.get(UpsertAsync(payload=mp_payload))['jobId']
                self.stdout.write(msg=f'Задача {mp_id}. Кол-во поставщиков {len(mp_payload)}')
                mp_payload = []
        if count%200==0:
            mp_id = site.get(UpsertAsync(payload=mp_payload))['jobId']
            self.stdout.write(msg=f'Задача {mp_id}. Кол-во поставщиков {len(mp_payload)}')
        self.stdout.write(self.style.SUCCESS('Выполнение завершено'))