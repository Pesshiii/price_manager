"""Строка ГП набора (без поставщика, себестоимость из комплектующих)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0012_drop_catalog_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='mainproduct',
            name='is_set',
            field=models.BooleanField(default=False, verbose_name='Строка набора'),
        ),
        migrations.AddConstraint(
            model_name='mainproduct',
            constraint=models.UniqueConstraint(condition=models.Q(('is_set', True)), fields=('product',),
                                               name='mainproduct_one_set_row_per_product'),
        ),
    ]
