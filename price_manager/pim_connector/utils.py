
from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier
from .api import site, Entity, EntityList, Where

def get_supplier_id(supplier: Supplier, create: bool = False, update: bool = False)->str:
    if not supplier.pim_id is None:
        return supplier.pim_id
    items = site.get(
        EntityList(
            name='supplier', 
            select=['id'], 
            where=[Where(attribute='priceManagerId', type='like', value=f'{supplier.id}')]
            )
        )['list']
    if len(items) == 1:
        return items[0]['id']
    item = site.post(EntityList(
            name = 'Account',
            payload = {
                    'name':supplier.name,
                    'role':'supplier',
                    'priceManagerId':f"{supplier.id}",
            }
        )
    )
    supplier.pim_id = item['id']
    supplier.save()
    return item['id']

def get_product_id(product: MainProduct, create: bool = False, update: bool = False)->str:
    if not product.pim_id is None:
        return product.pim_id
    items = site.get(
        EntityList(
            name='Product', 
            select=['id'], 
            where=[Where(attribute='priceManagerId', type='like', value=f'{product.id}')]
            )
        )['list']
    if len(items) == 1:
        return items[0]['id']
    item = site.post(EntityList(
        name = 'Product',
        payload = {
                'name':product.name, 
                'priceManagerId':f"{product.id}",
                'mpn': product.article, 
                'number': product.article,
        }
    ))
    product.pim_id = item['id']
    product.save()
    return item['id']