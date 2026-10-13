"""Товар — пара (артикул, бренд): уникальность артикула только при бренде.

Шаг 3 перехода «товар = бренд + артикул» (.claude/shift-to-product-brief.md
§0.6). Уникальный Lower(number) заменён уникальной парой (Lower(number), brand)
с условием brand IS NOT NULL: товары без бренда с одним артикулом — разные
товары, пока бренда нет.

Новое ограничение строго слабее старого, поэтому миграция чисто схемная: всё,
что было уникально по артикулу, уникально и по паре. Обычный индекс по
Lower(number) возвращает поиску по артикулу то, что раньше давал уникальный
индекс, — частичный индекс пары товары без бренда не покрывает.
"""
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0020_brand_code_active_brandalias'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='product',
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower('number'), models.F('brand'),
                condition=models.Q(('brand__isnull', False)),
                name='product_product_number_brand_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(django.db.models.functions.text.Lower('number'), name='product_product_number_lower'),
        ),
        migrations.RemoveConstraint(
            model_name='product',
            name='product_product_number_lower_uniq',
        ),
    ]
