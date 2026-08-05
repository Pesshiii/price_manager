from django.core.management.base import BaseCommand
from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from main_product_manager.pim_api import site, UpsertAsync, Job, EntityList, Where
from typing import Dict, List
from time import sleep

class Command(BaseCommand):
    help = "Вызовите эту команду чтобы насытить создать связь между Pim и PriceManager"

    def handle(self, *args, **options)->None:
        suppliers = Supplier.objects.all()
        products = MainProduct.objects.all().filter(pim_id__isnull=True).select_related('supplier', 'manufacturer')
        self.stdout.write(self.style.SUCCESS(f'Начало выполнения задачи. Число поставщиков: {suppliers.count()}, товаров: {products.count()}'))
        s_payload = []
        count = 0
        for supplier in suppliers:
            s_payload.append({'entity':'Account', 'payload':{'name':supplier.name, 'role': 'supplier'}})
            count += 1
            if count%1000==0:
                s_id = site.get(UpsertAsync(payload=s_payload))['jobId']
                self.stdout.write(msg=f'Задача {s_id}. Кол-во поставщиков {len(s_payload)}')
                s_payload = []
        if not count%1000==0:
            s_id = site.get(UpsertAsync(payload=s_payload))['jobId']
            self.stdout.write(msg=f'Задача {s_id}. Кол-во поставщиков {len(s_payload)}')
        count = 0
        mp_payload = []
        def _get_supplier_id(name: str)->str|None:
            items =  site.get(EntityList(name='Account', where=[Where(attribute='name', type='like', value=name)]))['list'][0]['id']
            return items[0]['id'] if len(items)>0 else None
        def _get_product_id(product: MainProduct)->str|None:
            items = site.get(
                    EntityList(name='Product', 
                    select=['id'], 
                    where=[Where(attribute='priceManagerId', type='like', value=f'{product.id}')])
                )['list']
            return items[0]['id'] if len(items)>0 else None
        for supplier in suppliers:
            s_id = _get_supplier_id(supplier.name)
            for product in products.filter(supplier=supplier):
                item = {
                    'entity':'Product', 
                    'payload':{
                        'priceManagerId':product.id,
                        'name':product.name, 
                        'mpn': product.article, 
                        'number': product.sku,
                        'defaultSupplierId':s_id,
                    }
                }
                if not product.manufacturer is None:
                    item['payload']['brand'] = {
                        'name': product.manufacturer.name
                    }
                mp_payload.append(
                        item
                    )
                count += 1
                if count%1000==0:
                    mp_id = site.get(UpsertAsync(payload=mp_payload))['jobId']
                    self.stdout.write(msg=f'Задача {mp_id}. Кол-во товаров {len(mp_payload)}')
                    mp_payload = []
        if count%1000==0:
            mp_id = site.get(UpsertAsync(payload=mp_payload))['jobId']
            self.stdout.write(msg=f'Задача {mp_id}. Кол-во товаров {len(mp_payload)}')
        self.stdout.write(self.style.SUCCESS('Создание связей'))
        for product in products:
            product.pim_id = _get_product_id(product)
        MainProduct.objects.bulk_update(products, fields=['pim_id'])
        self.stdout.write(self.style.SUCCESS('Выполнение завершено'))