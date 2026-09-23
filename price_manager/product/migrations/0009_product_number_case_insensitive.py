"""product.Product.number становится регистронезависимым.

Раньше number был обычным CharField(unique=True) — Postgres сравнивает varchar
побайтово, так что "ABC123" и "abc123" проходили unique-проверку как разные
строки и могли годами сосуществовать. Меняем ограничение на
UniqueConstraint(Lower('number')), поэтому сначала нужно свести уже
накопившиеся регистро-дубли к одной строке на каждый number без учёта
регистра — иначе AddConstraint упадёт на первом же совпадении.

Для каждой группы дублей (несколько строк с одинаковым Lower(number)):
  - если среди них уже есть строка, чей number целиком в нижнем регистре —
    она становится «победителем»: все MainProduct/SupplierFeedEntry/
    SupplierLink, ссылающиеся на остальные строки группы, перевязываются на
    неё, а сами остальные строки удаляются;
  - если такой строки нет — победителем становится первая по pk строка
    группы (к ней так же перевязываются и удаляются остальные), после чего
    её number приводится к нижнему регистру.

Строки, у которых нет регистро-дубля, не трогаем — только реально
конфликтующие группы.

SupplierLink.product — on_delete=CASCADE (см. product.0007): удаление
проигравшей строки без перевязки SupplierLink молча унесло бы связь
поставщика, поэтому проверяем все три ссылки на Product, а не только
MainProduct.

pim_id уникален по всей таблице, и на реальных данных (проверено через
prod-snapshot) КАЖДАЯ из 189 конфликтующих групп держит два разных pim_id —
обе строки когда-то были независимо запушены в PIM как разные
PriceManagerProduct. Ждать здесь единичных, разрешаемых руками конфликтов
неверно: это норма, а не исключение. Точно как 0007 обнулял pim_id пачкой и
оставлял reindex_pim_ids дотолкнуть его заново, здесь pim_id проигравшей
строки просто отбрасывается вместе с ней: строка победителя сохраняет свой
pim_id как есть (если он уже был), а если не было — забирает pim_id
проигравшей. Один из двух PriceManagerProduct на стороне PIM в результате
осиротеет молча — почистить его там миграция не может и не должна (внешний
API, не задача схемы), это остаётся отдельной, ручной работой над данными
PIM. Число задетых таким образом групп попадает в лог миграции.

Порядок шагов: сначала снимаем старое unique=True (следующий шаг переносит
и удаляет строки, так что колонка не должна мешать промежуточным
состояниям), затем чистим данные, затем добавляем
UniqueConstraint(Lower('number')).
"""

from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def merge_case_duplicate_numbers(apps, schema_editor):
    Product = apps.get_model('product', 'Product')
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    SupplierFeedEntry = apps.get_model('supplier_feed', 'SupplierFeedEntry')
    SupplierLink = apps.get_model('supplier_feed', 'SupplierLink')

    colliding_numbers = list(
        Product.objects.filter(number__isnull=False)
        .annotate(lower_number=Lower('number'))
        .values('lower_number')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .values_list('lower_number', flat=True)
    )

    groups_merged = 0
    rows_deleted = 0
    pim_id_conflicts = 0
    for lower_number in colliding_numbers:
        # iexact compiles to UPPER(...) = UPPER(...) on Postgres -- a different
        # expression than the Lower() the grouping above (and the constraint
        # this migration adds) uses. Re-fetch on the same expression so a
        # group can't be defined one way and re-read another.
        group = list(
            Product.objects.annotate(lower_number=Lower('number'))
            .filter(lower_number=lower_number)
            .order_by('pk')
        )
        winner = next((p for p in group if p.number == lower_number), group[0])
        losers = [p for p in group if p.pk != winner.pk]

        for loser in losers:
            if loser.pim_id and winner.pim_id and loser.pim_id != winner.pim_id:
                pim_id_conflicts += 1
            elif not winner.pim_id and loser.pim_id:
                winner.pim_id = loser.pim_id
            if not winner.name and loser.name:
                winner.name = loser.name
            if not winner.raw_data and loser.raw_data:
                winner.raw_data = loser.raw_data
            if not winner.brand_id and loser.brand_id:
                winner.brand_id = loser.brand_id

            winner.categories.add(*loser.categories.all())
            MainProduct.objects.filter(product_id=loser.pk).update(product_id=winner.pk)
            SupplierFeedEntry.objects.filter(product_id=loser.pk).update(product_id=winner.pk)
            SupplierLink.objects.filter(product_id=loser.pk).update(product_id=winner.pk)
            loser.delete()
            rows_deleted += 1

        winner.number = lower_number
        winner.save()
        groups_merged += 1

    # Django FKs are DEFERRABLE INITIALLY DEFERRED, so the rebinds and deletes
    # above leave FK-check trigger events queued on product_product until
    # commit. The AddConstraint below is a CREATE INDEX on that same table in
    # the same transaction, and Postgres refuses it while events are pending
    # ("cannot CREATE INDEX ... because it has pending trigger events").
    # Fire them now, then restore the default deferral.
    if groups_merged:
        schema_editor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        schema_editor.execute('SET CONSTRAINTS ALL DEFERRED')

    print(
        f'  0009: смерджено групп регистро-дублей: {groups_merged}, удалено строк: {rows_deleted}, '
        f'с конфликтом pim_id (id проигравшей отброшен): {pim_id_conflicts}'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0008_brand_and_product_search_vector'),
        ('main_product_manager', '0011_mainproduct_product_fk'),
        ('supplier_feed', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='number',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Артикул'),
        ),
        migrations.RunPython(merge_case_duplicate_numbers, reverse_code=migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.UniqueConstraint(Lower('number'), name='product_product_number_lower_uniq'),
        ),
    ]
