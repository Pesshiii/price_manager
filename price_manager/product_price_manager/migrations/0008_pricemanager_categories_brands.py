"""PriceManager.categories and PriceManager.brands — the rule's product scope.

Unlike the categories field dropped in 0006, a chosen category covers its
descendants (PriceManager._in_scope). Both start empty, which means "every
row", so existing rules keep their reach. The through tables PROTECT the
category and the brand: with an auto-created table, deleting the only brand of
a rule would silently empty its scope and widen it to every row.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0015_remove_product_pricing'),
        ('product_price_manager', '0007_rename_to_price_manager_ui'),
    ]

    operations = [
        migrations.CreateModel(
            name='PriceManagerBrand',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('brand', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='product.brand', verbose_name='Бренд')),
                ('price_manager', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='product_price_manager.pricemanager', verbose_name='Менеджер цен')),
            ],
            options={
                'verbose_name': 'Бренд менеджера цен',
                'verbose_name_plural': 'Бренды менеджеров цен',
            },
        ),
        migrations.AddField(
            model_name='pricemanager',
            name='brands',
            field=models.ManyToManyField(blank=True, related_name='pricemanagers', through='product_price_manager.PriceManagerBrand', to='product.brand', verbose_name='Бренды'),
        ),
        migrations.CreateModel(
            name='PriceManagerCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='product.category', verbose_name='Категория')),
                ('price_manager', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='product_price_manager.pricemanager', verbose_name='Менеджер цен')),
            ],
            options={
                'verbose_name': 'Категория менеджера цен',
                'verbose_name_plural': 'Категории менеджеров цен',
            },
        ),
        migrations.AddField(
            model_name='pricemanager',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='pricemanagers', through='product_price_manager.PriceManagerCategory', to='product.category', verbose_name='Категории'),
        ),
        migrations.AddConstraint(
            model_name='pricemanagerbrand',
            constraint=models.UniqueConstraint(fields=('price_manager', 'brand'), name='pricemanager_brand_uniq'),
        ),
        migrations.AddConstraint(
            model_name='pricemanagercategory',
            constraint=models.UniqueConstraint(fields=('price_manager', 'category'), name='pricemanager_category_uniq'),
        ),
    ]
