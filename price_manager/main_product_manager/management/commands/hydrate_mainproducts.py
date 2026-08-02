from django.core.management.base import BaseCommand
from ...models import MainProduct
from ....supplier_manager.models import Supplier
from ...pim_api import site, UpsertAsync, Job, EntityList, Where
from time import sleep

class Command(BaseCommand):
    help = "Вызовите эту команду чтобы насытить продукты информацией из API."

    def handle(self, *args, **options)->None:
        suppliers = Supplier.objects.all()
        s_payload = []
        for supplier in suppliers:
            s_payload.append({'entity':'Account', 'payload':{'name':supplier.name, 'role': 'supplier'}})
        def _wait_job(id:str)->str:
            status = site.get(Job(id=id))['status']
            while not status == 'success':
                sleep(5)
                status = site.get(Job(id=id))['status']
                if status == 'Failed':
                    raise(RuntimeError('Migrations failed. ', ' Id: ', id, ' Message:', site.get(Job(id=id))['message']))
            return status
        s_id = site.get(UpsertAsync(payload=s_payload))['jobId']
        _wait_job(s_id)
        mp_payload = []
        def _get_supplier_id(name: str)->str:
            return site.get(EntityList(name='Account', where=[Where(attribute='name', type='like', value=name)]))['list'][0]['id']
        products = MainProduct.objects.all()
        for product in products:
            mp_payload.append({'entity':'Product', 'payload':{'name':product.name, 'mpn': product.article, 'number': product.article, 'defaultSupplierId':_get_supplier_id(product.supplier.name)}})
        mp_id = site.get(UpsertAsync(payload=mp_payload))['jobId']
        self.stdout.write(msg=_wait_job(mp_id))