"""Товары без артикула: ГП-строки — на товар своего sku, пустые заготовки — удалить.

Откуда они: main_product_manager.0011 завёл по заготовке на каждый старый
pim_id, а у строк одного sku от разных поставщиков pim_id бывали разные — один
артикул получал два Product. product.0007 обнулил pim_id, и
backfill_product_numbers отдал sku первому из пары, второй остался без номера:
артикул уже занят. ГП-строки, остаток и наценки такого артикула разъехались по
двум товарам, а у товара без номера нет ни категорий, ни бренда.

Каждая ГП-строка такого товара уходит на товар своего sku (Lower — как у
уникальности number). Если такого нет, номер получает сама заготовка: её pk и
ссылки на неё сохраняются. Строка набора (is_set) на товаре, где строка набора
уже есть, перестаёт быть ею — одна на товар; sync_set_rows разберётся при
следующем update_prices.

Опустевшие заготовки удаляются, только если на них больше ничего не ссылается
(любая обратная связь, включая отходящие приложения: SupplierLink.product —
CASCADE). Что сюда не ложится — строка без sku или со слишком длинным sku,
заготовка со ссылками — останавливает миграцию: следующая делает number
NOT NULL, и угадывать артикул за людей ей нельзя.

Обратного хода по данным нет: перенесённые строки не помнят, откуда пришли.
"""

from django.db import migrations
from django.db.models import Q


def merge_numberless_products(apps, schema_editor):
    Product = apps.get_model('product', 'Product')
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    max_length = Product._meta.get_field('number').max_length
    name_max_length = Product._meta.get_field('name').max_length
    numberless = Q(number__isnull=True) | Q(number='')

    moved = renumbered = 0
    for placeholder in Product.objects.filter(numberless).order_by('pk'):
        for row in MainProduct.objects.filter(product=placeholder).order_by('pk'):
            sku = (row.sku or '').strip()
            if not sku or len(sku) > max_length:
                raise RuntimeError(
                    f'product.0016: у строки ГП pk={row.pk} на товаре без артикула pk={placeholder.pk} '
                    f'нет sku, по которому её можно перенести (пустой или длиннее {max_length}). '
                    f'Исправьте sku или перенесите строку вручную и повторите migrate.'
                )
            target = Product.objects.filter(number__iexact=sku).order_by('pk').first()
            if target is None and not placeholder.number:
                placeholder.number = sku
                if not placeholder.name:
                    placeholder.name = (row.name or '')[:name_max_length] or None
                placeholder.save(update_fields=['number', 'name'])
                renumbered += 1
                continue
            if target is None:
                target = Product.objects.create(
                    number=sku, name=(row.name or '')[:name_max_length] or None)
            if target.pk == placeholder.pk:
                continue
            if row.is_set and MainProduct.objects.filter(product=target, is_set=True).exists():
                row.is_set = False
            row.product = target
            row.save(update_fields=['product', 'is_set'])
            moved += 1

    leftover = Product.objects.filter(numberless)
    for relation in Product._meta.related_objects:
        model = relation.related_model
        if model._meta.auto_created:
            continue
        referenced = model._base_manager.filter(**{f'{relation.field.name}__in': leftover})
        if referenced.exists():
            raise RuntimeError(
                f'product.0016: на товары без артикула ссылается {model._meta.label}.'
                f'{relation.field.name} (например pk={referenced.values_list("pk", flat=True).first()}). '
                f'Дайте этим товарам артикул или уберите ссылки и повторите migrate.'
            )
    deleted, _ = leftover.delete()
    print(f'  0016: перенесено строк ГП: {moved}, заготовок получили артикул: {renumbered}, '
          f'удалено пустых заготовок: {deleted}')


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0015_remove_product_pricing'),
        ('main_product_manager', '0013_mainproduct_is_set'),
        ('core', '0013_persistentnotification_lifetime'),
    ]

    operations = [
        migrations.RunPython(merge_numberless_products, reverse_code=migrations.RunPython.noop),
    ]
