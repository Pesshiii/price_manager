"""MainProduct.pim_id (строка) → MainProduct.product (FK на product.Product).

Зеркало PIM живёт в product.Product, и хранить рядом с ним ещё и голый id
в main_product_manager означало две несвязанные копии одной связи.

Засеять таблицу зеркала здесь всё-таки приходится: product.0005 создал по
Product на каждый MainProduct.pim_id, который существовал НА ТОТ МОМЕНТ, а
_resolve_pim_id / create_pim_links / reindex_pim_ids_batch и импорт из выгрузки
писали pim_id и после него — для этих строк Product-а нет. Поэтому сначала
дозаполняем зеркало, и только потом проставляем FK.
"""

from django.db import migrations, models
from django.db.models import OuterRef, Subquery
import django.db.models.deletion


def link_products_to_pim_mirror(apps, schema_editor):
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    Product = apps.get_model('product', 'Product')
    max_length = Product._meta.get_field('pim_id').max_length

    linkable = MainProduct.objects.exclude(pim_id__isnull=True).exclude(pim_id='')
    pim_ids = set(linkable.order_by().values_list('pim_id', flat=True).distinct())

    # MainProduct.pim_id — varchar без ограничения длины, product.Product.pim_id
    # — max_length=64. Значение, которое никогда не влезало бы в зеркало,
    # пропускаем: такие MainProduct останутся непривязанными (product_id = NULL
    # им проставит тот же Subquery ниже, не найдя строки), а не уронят миграцию
    # целиком на DataError посреди bulk_create.
    too_long = sorted(p for p in pim_ids if len(p) > max_length)
    if too_long:
        print(
            f'  0011: пропущено pim_id длиннее {max_length} символов: {len(too_long)} '
            f'(например {too_long[0]!r}) — эти MainProduct останутся без привязки'
        )

    existing = set(Product.objects.order_by().values_list('pim_id', flat=True))
    missing = [p for p in sorted(pim_ids) if len(p) <= max_length and p not in existing]
    if missing:
        # Заготовки: только pim_id, number/name = NULL — ровно та же форма, что
        # кладёт product.0005 и product.services.pim_sync.sync_product_from_pim.
        Product.objects.bulk_create(
            [Product(pim_id=pim_id, number=None) for pim_id in missing],
            batch_size=1000,
        )
        print(f'  0011: создано заготовок product.Product: {len(missing)}')

    # Один коррелированный UPDATE, а не запрос на каждый pim_id: строк здесь
    # порядка 156k. Для pim_id, которого нет в зеркале (слишком длинный),
    # подзапрос вернёт NULL — товар просто остаётся непривязанным.
    updated = linkable.update(
        product_id=Subquery(
            Product.objects.filter(pim_id=OuterRef('pim_id')).values('id')[:1]
        )
    )
    print(f'  0011: привязано MainProduct: {updated}')


def unlink_products_from_pim_mirror(apps, schema_editor):
    """Обратный ход: вернуть строковый pim_id из связанного Product."""
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    Product = apps.get_model('product', 'Product')
    MainProduct.objects.filter(product__isnull=False).update(
        pim_id=Subquery(
            Product.objects.filter(id=OuterRef('product_id')).values('pim_id')[:1]
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0010_alter_mainproduct_pim_id'),
        ('product', '0006_alter_product_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='mainproduct',
            name='product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='main_products',
                to='product.product',
                verbose_name='Товар PIM',
            ),
        ),
        migrations.RunPython(
            link_products_to_pim_mirror,
            unlink_products_from_pim_mirror,
        ),
        migrations.RemoveField(
            model_name='mainproduct',
            name='pim_id',
        ),
    ]
