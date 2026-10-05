"""«Без поставщика» → «Свой склад», без подставных строк прайса.

0009 дал каждой ручной строке ГП служебного поставщика строку прайса
(SupplierProduct) с её остатком: только так update_stocks не обнулял остаток, и
только через строку прайса правило поставщика находило строку ГП. Теперь
update_stocks не трогает строку без строки прайса у любого поставщика, а правило
находит строки по поставщику строки ГП, — подставные строки прайса не нужны.

1. Служебный поставщик, если его имя ещё «Без поставщика», — «Свой склад»
   (если это имя не занято другим поставщиком).
2. Копии правил из 0009 с суффиксом « (без поставщика)» — « (свой склад)», если
   имя свободно. Переименованные руками не трогаются.
3. Подставные строки прайса удаляются — если у служебного поставщика нет ни
   одной настройки загрузки: тогда каждая его строка прайса подставная. Остаток
   строки ГП остаётся — он и так её. Если настройка есть, не удаляется ничего:
   строка, выпавшая из файла, выглядит так же (без настройки и цен), а без неё
   копирование в ГП завело бы для неё вторую строку ГП. Такую базу разбирать
   руками; на проде настроек у него нет.

Обратно не откатывается: удалённые строки прайса не восстановить.
"""
from django.db import migrations

OLD_NAME = 'Без поставщика'
NEW_NAME = 'Свой склад'
OLD_SUFFIX = ' (без поставщика)'
NEW_SUFFIX = ' (свой склад)'
SP_PRICES = ('supplier_price', 'rrp', 'discount_price')


def forwards(apps, schema_editor):
    Supplier = apps.get_model('supplier_manager', 'Supplier')
    PriceManager = apps.get_model('product_price_manager', 'PriceManager')
    SupplierProduct = apps.get_model('supplier_product_manager', 'SupplierProduct')
    Setting = apps.get_model('supplier_product_manager', 'Setting')

    supplier = Supplier.objects.filter(is_own_stock=True).first()
    if supplier is None:
        return
    if supplier.name == OLD_NAME and not Supplier.objects.filter(name=NEW_NAME).exists():
        supplier.name = NEW_NAME
        supplier.save(update_fields=['name'])

    names = set(PriceManager.objects.values_list('name', flat=True))
    for rule in PriceManager.objects.filter(supplier=supplier, name__endswith=OLD_SUFFIX):
        name = rule.name[:-len(OLD_SUFFIX)] + NEW_SUFFIX
        if name in names:
            continue
        names.discard(rule.name)
        names.add(name)
        rule.name = name
        rule.save(update_fields=['name'])

    if Setting.objects.filter(supplier=supplier).exists():
        return
    synthetic = SupplierProduct.objects.filter(
        supplier=supplier, source_settings__isnull=True, discount__isnull=True,
        **{f'{field}__isnull': True for field in SP_PRICES})
    SupplierProduct.objects.filter(pk__in=list(synthetic.values_list('pk', flat=True))).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0009_unsupplied_supplier'),
        ('supplier_manager', '0016_supplier_is_own_stock'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
