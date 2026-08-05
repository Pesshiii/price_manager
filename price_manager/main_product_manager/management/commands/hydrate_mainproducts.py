from django.core.management.base import BaseCommand
from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from main_product_manager.pim_api import site, UpsertAsync, Job, EntityList, Where, entityMassUpdate
from typing import Dict, List
from time import sleep

class Command(BaseCommand):
    help = "Вызовите эту команду чтобы насытить создать связь между Pim и PriceManager"

    def handle(self, *args, **options)->None:
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
                site.get(UpsertAsync(payload=s_payload))
                site.get(entityMassUpdate(payload=s_payload))
                self.stdout.write(msg=f'Обновлено {count} поставщиков.. Кол-во поставщиков {len(s_payload)}')
                s_payload = []
        if not count%1000==0:
            site.get(UpsertAsync(payload=s_payload))
            site.get(entityMassUpdate(payload=s_payload))
            self.stdout.write(msg=f'Обновлено {count} поставщиков. Кол-во поставщиков {len(s_payload)}')
        for supplier in suppliers:
            supplier.pim_id = _get_supplier_id(supplier)
        Supplier.objects.bulk_update(suppliers, fields=['pim_id'])
        count = 0
        mp_payload = []
        for product in products:
            item = {
                'entity':'Product', 
                'payload':{
                    'priceManagerId':product.id,
                    'name':product.name, 
                    'mpn': product.article, 
                    'number': product.sku,
                    'defaultSupplierId':product.supplier.pim_id,
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
                site.get(UpsertAsync(payload=mp_payload))
                site.get(entityMassUpdate(payload=mp_payload))
                self.stdout.write(msg=f'Обновлено {count} продуктов. Кол-во товаров {len(mp_payload)}')
                mp_payload = []
        if count%1000==0:
            self.stdout.write(msg=f'Обновлено {count} продуктов. Кол-во товаров {len(mp_payload)}')
        self.stdout.write(self.style.SUCCESS('Создание связей'))
        for product in products:
            product.pim_id = _get_product_id(product)
        MainProduct.objects.bulk_update(products, fields=['pim_id'])
        self.stdout.write(self.style.SUCCESS('Выполнение завершено'))