"""product.Product.pim_id меняет смысл: теперь это id PriceManagerProduct.

До этой миграции pim_id хранил id товара PIM (Product). Теперь связь с PIM —
сквозная запись PriceManagerProduct: её platformID — наш pk, productId — товар
PIM, а в pim_id лежит её собственный id. Старые значения под новый смысл не
подходят, поэтому обнуляются все; reindex_pim_ids заново найдёт товар PIM по
number и создаст PriceManagerProduct.

Порядок шагов важен: pim_id сначала становится nullable, иначе обнулять нечем.
После обнуления строки без pim_id, без number и без единой ссылки не имеют
вообще никакой идентичности — это заготовки product.0005 / main_product_manager.0011,
на которые больше ничего не указывает. Их удаляем. Проверяем все ссылки на
Product, а не только MainProduct: SupplierLink.product — on_delete=CASCADE, и
удаление «сироты» молча унесло бы связь поставщика.

Product.name перестаёт быть unique: несколько локальных Product могут указывать
на один товар PIM, а в PIM имя товара не уникально.

Обратного хода по данным нет: старые id товаров PIM после обнуления нигде не
сохранились, а удалённые заготовки не несли ничего, кроме такого id. Откат
схемы упрётся в NOT NULL на pim_id, пока в таблице есть строки без него.
"""

from django.db import migrations, models


def reset_pim_ids(apps, schema_editor):
    Product = apps.get_model('product', 'Product')
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    SupplierFeedEntry = apps.get_model('supplier_feed', 'SupplierFeedEntry')
    SupplierLink = apps.get_model('supplier_feed', 'SupplierLink')

    reset = Product.objects.exclude(pim_id__isnull=True).update(pim_id=None)
    print(f'  0007: обнулено pim_id: {reset}')

    residue = (
        Product.objects.filter(number__isnull=True)
        .exclude(pk__in=MainProduct.objects.filter(product__isnull=False).values('product_id'))
        .exclude(pk__in=SupplierFeedEntry.objects.filter(product__isnull=False).values('product_id'))
        .exclude(pk__in=SupplierLink.objects.filter(product__isnull=False).values('product_id'))
    )
    deleted, _ = residue.delete()
    print(f'  0007: удалено заготовок без number и без ссылок: {deleted}')


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0006_alter_product_name'),
        ('main_product_manager', '0011_mainproduct_product_fk'),
        ('supplier_feed', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='pim_id',
            field=models.CharField(
                blank=True, max_length=64, null=True, unique=True,
                verbose_name='Id связи в PIM (PriceManagerProduct)',
            ),
        ),
        migrations.RunPython(reset_pim_ids, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='number',
            field=models.CharField(blank=True, max_length=128, null=True, unique=True, verbose_name='Артикул'),
        ),
        migrations.AlterField(
            model_name='product',
            name='name',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='Название'),
        ),
    ]
