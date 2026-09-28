"""«Цены товаров» (product_pricing) убраны целиком — вместе с основными ценами
Product, которые существовали только как источник для их наценок.

Приложения больше нет в INSTALLED_APPS, поэтому его таблицы, записи
django_migrations и типы контента удаляются здесь. На свежей базе таблиц нет
вовсе — IF EXISTS.
"""
from django.db import migrations

PRODUCT_PRICING_TABLES = [
    'product_pricing_productprice',
    'product_pricing_productpricerule_products',
    'product_pricing_productpricerule_brands',
    'product_pricing_productpricerule_categories',
    'product_pricing_productpricerule',
    'product_pricing_productpricetype',
]

PRICE_FIELDS = [
    'prime_cost', 'wholesale_price', 'basic_price', 'm_price', 'wholesale_price_extra',
    'discount_price', 'kaspi_price', 'supplier_price', 'rrp', 'supplier_discount_price',
    'prices_updated_at',
]


def drop_product_pricing(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in PRODUCT_PRICING_TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS {schema_editor.quote_name(table)} CASCADE')
        cursor.execute("DELETE FROM django_migrations WHERE app = 'product_pricing'")
        # Типы контента — с правами и ссылками журнала админки на них.
        stale = "SELECT id FROM django_content_type WHERE app_label = 'product_pricing'"
        cursor.execute(f'UPDATE django_admin_log SET content_type_id = NULL WHERE content_type_id IN ({stale})')
        cursor.execute(f'DELETE FROM auth_permission WHERE content_type_id IN ({stale})')
        cursor.execute("DELETE FROM django_content_type WHERE app_label = 'product_pricing'")


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0014_remove_product_pim_pushed_prices'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('admin', '0003_logentry_add_action_flag_choices'),
    ]

    operations = [
        migrations.RunPython(drop_product_pricing, migrations.RunPython.noop),
        *[migrations.RemoveField(model_name='product', name=field) for field in PRICE_FIELDS],
    ]
