"""Строкам ПП без заявки о бренде — бренд товара их строки ГП. Разово.

Продолжение перехода «товар = бренд + артикул» (.claude/shift-to-product-brief.md
§0.6): бренд строки — половина пары (артикул, бренд). Бренд строки ПП —
сведённая заявка поставщика. Если поставщик бренда не называет (написания нет
или оно значит «бренда нет»), строка берёт бренд товара своей строки ГП.
Дальше правило держит сопоставление (product.services.brands.inherit_product_brands),
а миграция заполняет такие строки сразу, не дожидаясь ночного sync_brands.

Строки с написанием, которое ждёт сопоставления, не трогаются: их решают в окне
«Бренды». Обратно — у строк без заявки бренд снимается: до этого правила
сопоставление его им не ставило.
"""
import re

from django.db import migrations
from django.db.models import OuterRef, Q, Subquery


def brand_key(name):
    """product.models.brand_key на 2026-10-13. Копия: миграция не зависит от кода приложения."""
    return re.sub(r'[\s\-_.]+', '', (name or '').lower().replace('ё', 'е'))


def no_claim(apps):
    """Строки ПП без заявки: без написания или с написанием «бренда нет».

    «Бренда нет» — синоним «игнорировать» (BrandAlias без бренда) или одни
    разделители, как в BrandIndex.lookup.
    """
    SupplierProduct = apps.get_model('supplier_product_manager', 'SupplierProduct')
    BrandAlias = apps.get_model('product', 'BrandAlias')
    ignored = set(BrandAlias.objects.filter(brand__isnull=True).values_list('name_key', flat=True))
    names = SupplierProduct.objects.filter(brand_name__isnull=False).values_list('brand_name', flat=True).distinct()
    no_brand = [name for name in names if not brand_key(name) or brand_key(name) in ignored]
    return Q(brand_name__isnull=True) | Q(brand_name__in=no_brand)


def forwards(apps, schema_editor):
    SupplierProduct = apps.get_model('supplier_product_manager', 'SupplierProduct')
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    (SupplierProduct.objects.filter(no_claim(apps), brand__isnull=True, main_product__product__brand__isnull=False)
     .update(brand_id=Subquery(
         MainProduct.objects.filter(pk=OuterRef('main_product_id')).values('product__brand')[:1])))


def backwards(apps, schema_editor):
    SupplierProduct = apps.get_model('supplier_product_manager', 'SupplierProduct')
    SupplierProduct.objects.filter(no_claim(apps), brand__isnull=False).update(brand=None)


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0014_mainproduct_set_delivery_days'),
        ('product', '0021_product_number_brand_uniq'),
        ('supplier_product_manager', '0020_supplierproduct_brand'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
