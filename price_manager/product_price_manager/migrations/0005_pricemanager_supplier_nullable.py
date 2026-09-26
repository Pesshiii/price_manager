"""Наценка ГП без поставщика — на строки ГП без поставщика и строки наборов."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0004_categories_to_product_category'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pricemanager',
            name='supplier',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='pricemanagers', to='supplier_manager.supplier',
                                    verbose_name='Поставщик'),
        ),
    ]
