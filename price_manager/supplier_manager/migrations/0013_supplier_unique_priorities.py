"""Приоритеты поставщиков — сплошная нумерация 1…N без повторов.

До этой миграции приоритеты никто не проверял, так что в данных возможны и
совпадения, и пропуски. Перед ограничением проранжированные поставщики
перенумеровываются подряд с сохранением порядка: по старому номеру, при
равных — по имени. Дальше сплошность держит Supplier.place().
"""

from django.db import migrations, models


PRIORITY_FIELDS = ('price_priority', 'stock_priority')


def renumber(pairs):
    """[(pk, priority)] в порядке (priority, name) -> {pk: новый номер} для изменившихся."""
    return {pk: n for n, (pk, value) in enumerate(pairs, 1) if value != n}


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
