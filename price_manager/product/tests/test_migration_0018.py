import importlib

from django.apps import apps
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase

from product.models import Product

migration = importlib.import_module('product.migrations.0018_drop_api_stack')


class DropApiStackTests(TestCase):
    """The data step of product.0018, run against the live registry.

    CI migrates an empty database that never had the API apps' tables; this
    is the only place the step meets them. Each test recreates what production
    still holds — a table with an FK into product_product, a content type with
    a granted permission and an admin log entry, a django_migrations row — and
    the per-test rollback takes it all away again (Postgres DDL is
    transactional).
    """

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS supplier_feed_supplierlink CASCADE')
            cursor.execute(
                'CREATE TABLE supplier_feed_supplierlink ('
                ' id serial PRIMARY KEY,'
                ' product_id bigint REFERENCES product_product (id) DEFERRABLE INITIALLY DEFERRED)'
            )
        self.recorder = MigrationRecorder(connection)
        self.recorder.migration_qs.get_or_create(app='supplier_feed', name='0001_initial')
        self.content_type = ContentType.objects.get_or_create(app_label='supplier_feed', model='supplierlink')[0]
        self.permission = Permission.objects.create(
            content_type=self.content_type, codename='view_supplierlink', name='Can view supplier link')
        self.user = User.objects.create_user('editor')
        self.user.user_permissions.add(self.permission)
        Group.objects.create(name='Редакторы').permissions.add(self.permission)
        self.log_entry = LogEntry.objects.create(
            user=self.user, content_type=self.content_type, object_id='1',
            object_repr='link', action_flag=ADDITION)

    def _run(self):
        with connection.schema_editor(atomic=False) as schema_editor:
            migration.drop_api_stack(apps, schema_editor)

    def test_drops_tables_and_migration_records(self):
        self._run()

        self.assertNotIn('supplier_feed_supplierlink', connection.introspection.table_names())
        self.assertFalse(self.recorder.migration_qs.filter(app__in=migration.API_APPS).exists())
        self.assertTrue(self.recorder.migration_qs.filter(app='supplier_manager').exists())

    def test_product_stops_being_held_by_the_dropped_fk(self):
        product = Product.objects.create(number='SKU-1')
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO supplier_feed_supplierlink (product_id) VALUES (%s)', [product.pk])

        self._run()

        product.delete()
        with connection.cursor() as cursor:
            # Would raise IntegrityError while the FK still existed.
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')

    def test_removes_content_types_with_their_permissions(self):
        live = ContentType.objects.get_for_model(Product)

        self._run()

        self.assertFalse(ContentType.objects.filter(app_label__in=migration.API_APPS).exists())
        self.assertFalse(Permission.objects.filter(pk=self.permission.pk).exists())
        self.assertFalse(self.user.user_permissions.exists())
        self.assertFalse(Permission.objects.filter(group__name='Редакторы').exists())
        self.log_entry.refresh_from_db()
        self.assertIsNone(self.log_entry.content_type_id)
        self.assertTrue(ContentType.objects.filter(pk=live.pk).exists())
        self.assertTrue(Permission.objects.filter(content_type=live).exists())
