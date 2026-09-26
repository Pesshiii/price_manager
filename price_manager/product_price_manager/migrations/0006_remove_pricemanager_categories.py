"""Drop PriceManager.categories.

The field scoped a markup rule to exact product.Category nodes (no
descendants). Category-based pricing lives on the second level
(product_pricing.ProductPriceRule, with descendants), and the ГП rule form no
longer offers it.

Dropping the field also drops its filter: a rule that had categories would
silently widen to every row of its supplier on the next save()/apply() and
rewrite their prices. So, like 0004, the migration refuses to run while any
rule is scoped instead of dropping the scope under it.
"""

from django.db import migrations


def refuse_if_any_rule_is_scoped(apps, schema_editor):
    PriceManager = apps.get_model('product_price_manager', 'PriceManager')
    scoped = list(
        PriceManager.objects.filter(categories__isnull=False).distinct().values_list('pk', flat=True)
    )
    if scoped:
        raise RuntimeError(
            f'0006: у {len(scoped)} правил наценки заданы категории (pk: {scoped}). '
            'Удаление поля сделало бы их правилами на ВСЕ товары поставщика. '
            'Перенесите такие наценки в «Цены товаров» или удалите/сделайте устаревшими, '
            'уберите у них категории и запустите миграцию снова.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0005_pricemanager_supplier_nullable'),
    ]

    operations = [
        migrations.RunPython(refuse_if_any_rule_is_scoped, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='pricemanager',
            name='categories',
        ),
    ]
