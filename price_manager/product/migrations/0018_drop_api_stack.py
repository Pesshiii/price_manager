"""API-версия (pricing, supplier, supplier_feed, dataframe) убрана целиком.

Приложений больше нет в INSTALLED_APPS, поэтому их таблицы, записи
django_migrations и типы контента удаляются здесь — как product_pricing в 0015.
Таблицы держат внешние ключи на product_product и product_category, и,
оставшись, мешали бы удалять товары и категории. Записи django_migrations
убираются, чтобы будущее приложение с тем же именем (supplier, pricing) не
посчитало свою 0001 уже применённой. На свежей базе таблиц нет вовсе — IF EXISTS.
"""
from django.db import migrations

API_APPS = ['pricing', 'supplier', 'supplier_feed', 'dataframe']

API_TABLES = [
    'supplier_feed_supplierlink',
    'supplier_feed_supplierfeedentry',
    'supplier_feed_feedcolumnmapping',
    'supplier_feed_supplierfeed',
    'supplier_feed_feedmapping',
    'pricing_pricingrule',
    'pricing_pricetype',
    'supplier_supplier',
    'dataframe_dataframe',
]


def drop_api_stack(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in API_TABLES:
            cursor.execute(f'DROP TABLE IF EXISTS {schema_editor.quote_name(table)} CASCADE')
        cursor.execute('DELETE FROM django_migrations WHERE app = ANY(%s)', [API_APPS])
        # Типы контента — с правами (и их выдачей пользователям и группам)
        # и ссылками журнала админки на них.
        stale = 'SELECT id FROM django_content_type WHERE app_label = ANY(%s)'
        permissions = f'SELECT id FROM auth_permission WHERE content_type_id IN ({stale})'
        cursor.execute(f'DELETE FROM auth_user_user_permissions WHERE permission_id IN ({permissions})', [API_APPS])
        cursor.execute(f'DELETE FROM auth_group_permissions WHERE permission_id IN ({permissions})', [API_APPS])
        cursor.execute(f'UPDATE django_admin_log SET content_type_id = NULL WHERE content_type_id IN ({stale})', [API_APPS])
        cursor.execute(f'DELETE FROM auth_permission WHERE content_type_id IN ({stale})', [API_APPS])
        cursor.execute('DELETE FROM django_content_type WHERE app_label = ANY(%s)', [API_APPS])


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0017_product_number_not_null'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('admin', '0003_logentry_add_action_flag_choices'),
    ]

    operations = [
        migrations.RunPython(drop_api_stack, migrations.RunPython.noop),
    ]
