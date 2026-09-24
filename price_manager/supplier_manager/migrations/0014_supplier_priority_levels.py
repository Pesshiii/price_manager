from django.db import migrations, models

PRIORITY_HELP = ('Меньше — выше. Один уровень у нескольких поставщиков — '
                 'цены — у того, чья себестоимость меньше, остаток — максимальный. '
                 'Пусто — общий нижний уровень.')


class Migration(migrations.Migration):
    """Приоритеты становятся уровнями: один номер у нескольких поставщиков.

    Данные не трогаются: сплошные 1…N из 0013 — это N уровней по одному
    поставщику, и основное значение считается так же, как до перехода.
    """

    dependencies = [
        ('supplier_manager', '0013_supplier_unique_priorities'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='supplier',
            name='supplier_unique_price_priority',
        ),
        migrations.RemoveConstraint(
            model_name='supplier',
            name='supplier_unique_stock_priority',
        ),
        migrations.AlterField(
            model_name='supplier',
            name='price_priority',
            field=models.PositiveIntegerField(blank=True, help_text=PRIORITY_HELP, null=True, verbose_name='Уровень по цене'),
        ),
        migrations.AlterField(
            model_name='supplier',
            name='stock_priority',
            field=models.PositiveIntegerField(blank=True, help_text=PRIORITY_HELP, null=True, verbose_name='Уровень по остаткам'),
        ),
    ]
