"""Бренд из прайса поставщика: сырое написание и бренд PIM, к которому оно сведено.

Колонку производителя убрали в 0010 (Phase 2b, D11). Политика «товар =
(бренд, артикул)» возвращает её, но уже как заявку, сопоставляемую с брендом
PIM синонимом (product.BrandAlias), а не как отдельный справочник.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0020_brand_code_active_brandalias'),
        ('supplier_product_manager', '0019_setting_has_header'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierproduct',
            name='brand_name',
            field=models.CharField(blank=True, db_index=True, null=True, verbose_name='Бренд поставщика'),
        ),
        migrations.AddField(
            model_name='supplierproduct',
            name='brand',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='supplier_products', to='product.brand', verbose_name='Бренд'),
        ),
        migrations.AlterField(
            model_name='link',
            name='key',
            field=models.CharField(choices=[('', 'Не включать'), ('article', 'Артикул поставщика'), ('name', 'Название'), ('brand_name', 'Бренд'), ('description', 'Описание'), ('discount', 'Группа скидок'), ('stock', 'Остаток'), ('supplier_price', 'Цена поставщика в валюте поставщика'), ('rrp', 'РРЦ в валюте поставщика'), ('discount_price', 'Цена со скидкой в валюте поставщика')]),
        ),
    ]
