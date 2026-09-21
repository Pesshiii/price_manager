"""PriceManager.categories: supplier_manager.Category -> product.Category (Phase 2b, D4).

Django cannot AlterField an M2M onto a different model, so the field is removed
and added again — which empties it. That is safe only while no rule uses
category scoping (measured G4 = 0), and it must stay safe by construction, not by
measurement: get_fitting_mps treats an empty `categories` as "every product of
the supplier". A rule that silently lost its categories here would widen to the
whole catalogue on its next save()/apply() and rewrite prices for all of it.
So the migration refuses to run instead.
"""

from django.db import migrations, models


def refuse_if_any_rule_is_scoped(apps, schema_editor):
    PriceManager = apps.get_model('product_price_manager', 'PriceManager')
    scoped = list(
        PriceManager.objects.filter(categories__isnull=False).distinct().values_list('pk', flat=True)
    )
    if scoped:
        raise RuntimeError(
            f'0004: у {len(scoped)} правил наценки заданы категории (pk: {scoped}). '
            'Удаление поля сделало бы их правилами на ВСЕ товары поставщика. '
            'Перенесите их категории на product.Category вручную или уберите их, '
            'затем запустите миграцию снова.'
        )
    print()
    print('  0004: правил с категориями нет — поле пересоздаётся пустым')


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0003_alter_pricemanager_markup_alter_pricetag_markup'),
        ('product', '0008_brand_and_product_search_vector'),
    ]

    operations = [
        migrations.RunPython(refuse_if_any_rule_is_scoped, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='pricemanager',
            name='categories',
        ),
        migrations.AddField(
            model_name='pricemanager',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='pricemanagers',
                                         to='product.category', verbose_name='Категории'),
        ),
    ]
