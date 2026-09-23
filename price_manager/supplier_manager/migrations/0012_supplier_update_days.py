"""Частота обновления: выбор из трёх меток -> произвольный интервал в днях.

`price_update_rate`/`stock_update_rate` хранили ключ `TIME_FREQ` (метку, а не
число). Метки переводятся в дни, пустая — в NULL («не отслеживать»). Обратный
ход округляет интервал к ближайшей метке, так что откат теряет точность, но
не падает.
"""

from django.db import migrations, models

# Снимок models.TIME_FREQ на момент миграции — из models.py он удалён.
TIME_FREQ = {
    '': 0,
    'Каждый день': 1,
    'Каждую неделю': 7,
    'Каждые три недели': 21,
}


def rate_to_days(rate):
    return TIME_FREQ.get(rate or '') or None


def days_to_rate(days):
    if not days:
        return ''
    labels = [label for label in TIME_FREQ if label]
    return min(labels, key=lambda label: abs(TIME_FREQ[label] - days))


def forwards(apps, schema_editor):
    Supplier = apps.get_model('supplier_manager', 'Supplier')
    for supplier in Supplier.objects.all():
        supplier.price_update_days = rate_to_days(supplier.price_update_rate)
        supplier.stock_update_days = rate_to_days(supplier.stock_update_rate)
        supplier.save(update_fields=['price_update_days', 'stock_update_days'])


def backwards(apps, schema_editor):
    Supplier = apps.get_model('supplier_manager', 'Supplier')
    for supplier in Supplier.objects.all():
        supplier.price_update_rate = days_to_rate(supplier.price_update_days)
        supplier.stock_update_rate = days_to_rate(supplier.stock_update_days)
        supplier.save(update_fields=['price_update_rate', 'stock_update_rate'])


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0011_retire_category_and_manufacturer'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplier',
            name='price_update_days',
            field=models.PositiveIntegerField(blank=True, help_text='В днях. Пусто — не отслеживать.', null=True, verbose_name='Интервал обновления цен'),
        ),
        migrations.AddField(
            model_name='supplier',
            name='stock_update_days',
            field=models.PositiveIntegerField(blank=True, help_text='В днях. Пусто — не отслеживать.', null=True, verbose_name='Интервал обновления остатков'),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='supplier',
            name='price_update_rate',
        ),
        migrations.RemoveField(
            model_name='supplier',
            name='stock_update_rate',
        ),
    ]
