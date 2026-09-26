"""Строки ГП без поставщика: строка набора и комментарий."""

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
        migrations.AddField(
            model_name='mainproduct',
            name='note',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='Комментарий'),
        ),
        migrations.AddConstraint(
            model_name='mainproduct',
            constraint=models.UniqueConstraint(condition=models.Q(('is_set', True)), fields=('product',),
                                               name='mainproduct_one_set_row_per_product'),
        ),
    ]
