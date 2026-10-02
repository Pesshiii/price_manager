"""Строки ГП без поставщика — к служебному поставщику «Без поставщика».

До этой миграции «без поставщика» было supplier = NULL: возвраты, бонусы,
остатки и строки наборов вместе. Теперь у возвратов, бонусов и остатков есть
настоящий поставщик (Supplier.is_unsupplied) — с загрузкой, копированием в ГП,
менеджерами цен и уровнями, как у любого. NULL остаётся только у строк наборов.

1. Служебный поставщик создаётся (или помечается уже существующий с этим именем).
2. Строки ГП с NULL, кроме строк наборов, переходят к нему. Каждой — строка
   прайса (SupplierProduct) с её остатком: update_stocks берёт остаток строки ГП
   из прайса, и без неё первый же прогон обнулил бы введённое руками.
3. Менеджер цен без поставщика покрывал и эти строки, и строки наборов. Чтобы
   ничего не поменялось в ценах, у каждого такого менеджера появляется копия на
   служебного поставщика, и наценки (PriceTag) перенесённых строк переходят к
   копии. Исходный остаётся — на строки наборов.

Обратно не откатывается: какие строки были «без поставщика», после неё уже не
отличить от загруженных в служебного поставщика.
"""
from django.db import migrations

UNSUPPLIED_NAME = 'Без поставщика'
RULE_SUFFIX = ' (без поставщика)'
CLONED_FIELDS = ('has_rrp', 'date_from', 'date_to', 'source', 'dest', 'price_from',
                 'price_to', 'fixed_price', 'markup', 'increase', 'deprecated')


def _unsupplied(Supplier):
    supplier = Supplier.objects.filter(is_unsupplied=True).first()
    if supplier is None:
        supplier, _ = Supplier.objects.update_or_create(name=UNSUPPLIED_NAME,
                                                        defaults={'is_unsupplied': True})
    return supplier


def _move_rows(apps, supplier):
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    SupplierProduct = apps.get_model('supplier_product_manager', 'SupplierProduct')
    rows = list(MainProduct.objects.filter(supplier__isnull=True, is_set=False).order_by('pk'))
    if not rows:
        return []
    with_price_list = set(SupplierProduct.objects.filter(main_product__in=rows)
                          .values_list('main_product_id', flat=True))
    taken = set(SupplierProduct.objects.filter(supplier=supplier).values_list('article', 'name'))
    price_rows = []
    for row in rows:
        row.supplier_id = supplier.pk
        if row.pk in with_price_list:
            continue
        article = row.article or row.sku or str(row.pk)
        name = row.name or row.sku or article
        if (article, name) in taken:
            name = f'{name} #{row.pk}'
        taken.add((article, name))
        price_rows.append(SupplierProduct(supplier_id=supplier.pk, main_product_id=row.pk,
                                          article=article, name=name, stock=row.stock))
    MainProduct.objects.bulk_update(rows, ['supplier'], batch_size=1000)
    SupplierProduct.objects.bulk_create(price_rows, batch_size=1000)
    return [row.pk for row in rows]


def _split_rules(apps, supplier, moved):
    PriceManager = apps.get_model('product_price_manager', 'PriceManager')
    PriceManagerCategory = apps.get_model('product_price_manager', 'PriceManagerCategory')
    PriceManagerBrand = apps.get_model('product_price_manager', 'PriceManagerBrand')
    PriceTag = apps.get_model('product_price_manager', 'PriceTag')
    names = set(PriceManager.objects.values_list('name', flat=True))
    for rule in PriceManager.objects.filter(supplier__isnull=True).order_by('pk'):
        name = f'{rule.name}{RULE_SUFFIX}'
        n = 2
        while name in names:
            name = f'{rule.name}{RULE_SUFFIX} {n}'
            n += 1
        names.add(name)
        clone = PriceManager.objects.create(
            name=name, supplier=supplier,
            **{field: getattr(rule, field) for field in CLONED_FIELDS})
        PriceManagerCategory.objects.bulk_create(
            PriceManagerCategory(price_manager=clone, category_id=category_id)
            for category_id in PriceManagerCategory.objects.filter(price_manager=rule)
            .values_list('category_id', flat=True))
        PriceManagerBrand.objects.bulk_create(
            PriceManagerBrand(price_manager=clone, brand_id=brand_id)
            for brand_id in PriceManagerBrand.objects.filter(price_manager=rule)
            .values_list('brand_id', flat=True))
        # Свои ценники у копии бывают, только если save() модели их уже собрал
        # (не историческая модель, а живая — так её зовут тесты).
        PriceTag.objects.filter(p_manager=clone, mp_id__in=moved).delete()
        PriceTag.objects.filter(p_manager=rule, mp_id__in=moved).update(p_manager=clone)


def forwards(apps, schema_editor):
    Supplier = apps.get_model('supplier_manager', 'Supplier')
    supplier = _unsupplied(Supplier)
    moved = _move_rows(apps, supplier)
    _split_rules(apps, supplier, moved)


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0008_pricemanager_categories_brands'),
        ('supplier_manager', '0015_supplier_is_unsupplied'),
        ('main_product_manager', '0014_mainproduct_set_delivery_days'),
        ('supplier_product_manager', '0019_setting_has_header'),
        # product.0016 снимает is_set со второй строки набора на товаре — она
        # остаётся без поставщика и должна уйти к «Без поставщика» здесь.
        ('product', '0017_product_number_not_null'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
