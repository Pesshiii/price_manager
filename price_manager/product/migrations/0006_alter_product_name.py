from django.db import migrations, models
from django.db.models import Count


def nullify_empty_sentinels(apps, schema_editor):
    """Convert the '' sentinel to NULL for `name` and `number`, then verify
    `name` can actually take a unique constraint.

    0005 bulk-creates a Product per MainProduct.pim_id without touching
    `name`, so under name's old NOT NULL definition every seeded row carries
    ''. Postgres treats NULLs as distinct in a unique index but '' as equal,
    so the constraint added below would collide on all of them at once.

    `number` needs the same cleanup for a different reason: pim_sync wrote
    '' whenever PIM had no number. It is already unique+nullable (0004), so
    at most one such row can exist -- but it blocks the next nameless
    product from ever syncing, which is the bug this migration's companion
    change to pim_sync fixes.
    """
    Product = apps.get_model('product', 'Product')
    Product.objects.filter(name='').update(name=None)
    Product.objects.filter(number='').update(number=None)

    # PIM is not known to guarantee unique product names -- variants sharing
    # one display name are the usual way this breaks. Surface the conflict
    # with the offending values instead of a bare IntegrityError naming only
    # an index.
    duplicates = list(
        Product.objects.filter(name__isnull=False)
        .values('name')
        .annotate(n=Count('name'))
        .filter(n__gt=1)
        .values_list('name', flat=True)[:10]
    )
    if duplicates:
        raise RuntimeError(
            'Cannot make Product.name unique: duplicate names present. '
            f'First {len(duplicates)}: {duplicates}. '
            'Either deduplicate these rows or drop unique=True from '
            'Product.name in product/models.py and regenerate this migration.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0005_seed_products_from_main_product_pim_ids'),
    ]

    # Three steps, deliberately. The column must become nullable before the
    # data migration can write NULLs into it, and the '' rows must be gone
    # before the unique constraint goes on. Collapsing these into a single
    # AlterField passes CI -- where 0005 seeds nothing into an empty test
    # database -- and fails on any populated one.
    operations = [
        migrations.AlterField(
            model_name='product',
            name='name',
            field=models.CharField(blank=True, max_length=512, null=True, verbose_name='Название'),
        ),
        migrations.RunPython(nullify_empty_sentinels, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='name',
            field=models.CharField(blank=True, max_length=512, null=True, unique=True, verbose_name='Название'),
        ),
    ]
