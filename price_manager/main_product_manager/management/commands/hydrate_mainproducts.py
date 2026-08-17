from django.core.management.base import BaseCommand
from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from main_product_manager.pim_api import site, UpsertAsync, Job, EntityList, Where
from typing import Dict, List
from time import sleep
from main_product_manager.tasks import create_pim_links_task

class Command(BaseCommand):
    help = "Вызовите эту команду чтобы насытить создать связь между Pim и PriceManager"

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-create',
            action='store_true',
            help='Создавать новые записи в PIM',
        )


    def handle(self, *args, **options)->None:
        bypass_create = options['no_create']
        def _get_supplier_id(supplier)->str|None:
            items =  site.get(
                    EntityList(name='Account', 
                    select=['id'], 
                    where=[Where(attribute='priceManagerId', type='like', value=f'{supplier.id}')])
                )['list']
            return items[0]['id'] if len(items)>0 else None
        def _get_product_id(product: MainProduct)->str|None:
            items = site.get(
                    EntityList(name='Product', 
                    select=['id'], 
                    where=[Where(attribute='priceManagerId', type='like', value=f'{product.id}')])
                )['list']
            return items[0]['id'] if len(items)>0 else None
        suppliers = Supplier.objects.all().filter(pim_id__isnull=True)
        products = MainProduct.objects.all().filter(pim_id__isnull=True).select_related('supplier', 'manufacturer')
        self.stdout.write(self.style.SUCCESS(f'Начало выполнения задачи. Число поставщиков: {suppliers.count()}, товаров: {products.count()}'))
        s_payload : List[Dict[str, str|Dict[str, str|Dict[str, str]]]] = []
        count = 0
        for supplier in suppliers:
            s_payload.append(
                {
                    'entity':'Account', 
                    'payload':{
                        'name': f'{supplier.name}', 
                        'role': 'supplier',
                        'priceManagerId': f'{supplier.id}'
                    }
                }
                )
            count += 1
            if count%1000==0:
                if not bypass_create:
                    site.get(UpsertAsync(payload=s_payload))
                self.stdout.write(msg=f'Создано {count} поставщиков. Кол-во поставщиков {len(s_payload)}')
                s_payload = []
        if not count%1000==0:
            if not bypass_create:
                site.get(UpsertAsync(payload=s_payload))
            self.stdout.write(msg=f'Создано {count} поставщиков. Кол-во поставщиков {len(s_payload)}')
        for supplier in suppliers:
            supplier.pim_id = _get_supplier_id(supplier)
        Supplier.objects.bulk_update(suppliers, fields=['pim_id'])
        count = 0
        mp_payload = []
        for product in products:
            item = {
                'entity':'Product', 
                'payload':{
                    'name':product.name, 
                    'priceManagerId':f"{product.id}",
                    'mpn': product.article, 
                    'number': product.article,
                    'defaultSupplierId':product.supplier.pim_id,
                }
            }
            mp_payload.append(
                    item
                )
            count += 1
            if count%1000==0:
                if not bypass_create:
                    site.get(UpsertAsync(payload=mp_payload))
                self.stdout.write(msg=f'Создано {count} продуктов. Кол-во товаров {len(mp_payload)}')
                mp_payload = []
        if not count%1000==0:
            if not bypass_create:
                site.get(UpsertAsync(payload=mp_payload))
            self.stdout.write(msg=f'Создано {count} продуктов. Кол-во товаров {len(mp_payload)}')
        self.stdout.write(self.style.SUCCESS('Создание связей'))
        count = 0
        batch = []
        for product in products:
            if product.pim_id is None:
                batch.append(product.id)
                count += 1
            if count%1000==0:
                create_pim_links_task.delay(batch, user_id=1)
                self.stdout.write(msg=f'Создано {count} задач на создание связей')
                batch = []
        if not count%1000==0:
            create_pim_links_task.delay(batch, user_id=1)
            self.stdout.write(msg=f'Создано {count} задач на создание связей')
        self.stdout.write(self.style.SUCCESS('Выполнение завершено'))