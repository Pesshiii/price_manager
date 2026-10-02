"""Product.number — обязателен: NOT NULL и не пустая строка.

Отдельно от 0016: там удаляются строки с отложенными (DEFERRABLE) внешними
ключами на них, а ALTER TABLE в той же транзакции Postgres не даёт сделать,
пока висят неотработанные триггеры.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0016_merge_numberless_products'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='number',
            field=models.CharField(max_length=128, verbose_name='Артикул'),
        ),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.CheckConstraint(
                condition=models.Q(('number', ''), _negated=True),
                name='product_product_number_not_blank',
            ),
        ),
    ]
