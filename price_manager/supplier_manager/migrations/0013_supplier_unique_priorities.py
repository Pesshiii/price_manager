"""Приоритеты поставщиков уникальны.

До этой миграции приоритеты никто не проверял, так что совпадения в данных
возможны. Перед ограничением они разводятся с сохранением порядка: при
равных номерах выше остаётся поставщик, который раньше по имени, остальные
получают следующий свободный номер, а номера ниже по списку сдвигаются ровно
настолько, чтобы не столкнуться. Порядок поставщиков при этом не меняется.
"""

from django.db import migrations, models


PRIORITY_FIELDS = ('price_priority', 'stock_priority')


def renumber(pairs):
    """[(pk, priority)] в порядке (priority, name) -> {pk: новый номер} для изменившихся."""
    changed = {}
    last = None
    for pk, value in pairs:
        new = value if last is None or value > last else last + 1
        if new != value:
            changed[pk] = new
        last = new
    return changed


def resolve_duplicates(apps, schema_editor):
    Supplier = apps.get_model('supplier_manager', 'Supplier')
    for field in PRIORITY_FIELDS:
        pairs = list(
            Supplier.objects.filter(**{f'{field}__isnull': False})
            .order_by(field, 'name')
            .values_list('pk', field)
        )
        for pk, value in renumber(pairs).items():
            Supplier.objects.filter(pk=pk).update(**{field: value})
    # UPDATE оставляет отложенные триггеры (FK у Django DEFERRABLE), а с ними
    # Postgres не даёт AddConstraint в той же транзакции: «cannot ALTER TABLE
    # ... because it has pending trigger events». Пустая база CI этого не
    # видит — только база с данными.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0012_supplier_update_days'),
    ]

    operations = [
        migrations.RunPython(resolve_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(deferrable=models.Deferrable['DEFERRED'], fields=('price_priority',), name='supplier_unique_price_priority'),
        ),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(deferrable=models.Deferrable['DEFERRED'], fields=('stock_priority',), name='supplier_unique_stock_priority'),
        ),
    ]
