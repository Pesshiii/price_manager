from datetime import timedelta
from django.test import TestCase

from supplier_manager.models import Manufacturer, ManufacturerDict
from .resources import ManufacturerWidget


class ManufacturerWidgetTests(TestCase):
    def setUp(self):
        self.widget = ManufacturerWidget(Manufacturer, "name")

    def test_clean_uses_existing_manufacturer_case_insensitive(self):
        manufacturer = Manufacturer.objects.create(name="Bosch")

        result = self.widget.clean("bosch")

        self.assertEqual(result, manufacturer)
        self.assertEqual(Manufacturer.objects.count(), 1)

    def test_clean_uses_dictionary_mapping(self):
        manufacturer = Manufacturer.objects.create(name="DeWALT")
        ManufacturerDict.objects.create(name="Dewalt tools", manufacturer=manufacturer)

        result = self.widget.clean("dewalt tools")

        self.assertEqual(result, manufacturer)
        self.assertEqual(Manufacturer.objects.count(), 1)

    def test_clean_autobinds_close_name_to_existing_manufacturer(self):
        manufacturer = Manufacturer.objects.create(name="Makita")

        result = self.widget.clean("Makitta")

        self.assertEqual(result, manufacturer)
        self.assertTrue(
            ManufacturerDict.objects.filter(name="Makitta", manufacturer=manufacturer).exists()
        )
        self.assertEqual(Manufacturer.objects.count(), 1)

    def test_clean_creates_new_manufacturer_when_no_match(self):
        result = self.widget.clean("Completely New Brand")

        self.assertEqual(result.name, "Completely New Brand")
        self.assertEqual(Manufacturer.objects.count(), 1)

from django.utils import timezone

from supplier_manager.models import Currency, Supplier
from supplier_product_manager.models import SupplierProduct
from .models import MainProduct, MainProductLog
from .functions import merge_selected_main_products


class MergeSelectedMainProductsTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Test supplier',
            currency=self.currency,
            price_update_rate='',
            stock_update_rate='',
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def test_merges_products_using_oldest_log_as_original(self):
        older_product = MainProduct.objects.create(
            supplier=self.supplier,
            article='A-1',
            name='Дрель',
        )
        newer_product = MainProduct.objects.create(
            supplier=self.supplier,
            article='A-2',
            name='Дрель',
        )

        MainProductLog.objects.create(
            main_product=older_product,
            update_time=timezone.now() - timedelta(days=10),
            stock=5,
        )
        MainProductLog.objects.create(
            main_product=newer_product,
            update_time=timezone.now() - timedelta(days=1),
            stock=2,
        )

        SupplierProduct.objects.create(
            main_product=newer_product,
            supplier=self.supplier,
            article='SP-1',
            name='Позиция поставщика',
        )

        keep_product, deleted_products, moved_supplier_products, moved_logs = merge_selected_main_products(
            [older_product.id, newer_product.id]
        )

        self.assertEqual(keep_product.id, older_product.id)
        self.assertEqual(deleted_products, 1)
        self.assertEqual(moved_supplier_products, 1)
        self.assertEqual(moved_logs, 1)
        self.assertFalse(MainProduct.objects.filter(id=newer_product.id).exists())
        self.assertTrue(
            SupplierProduct.objects.filter(main_product=older_product, article='SP-1').exists()
        )

    def test_returns_none_when_less_than_two_products_selected(self):
        product = MainProduct.objects.create(
            supplier=self.supplier,
            article='A-1',
            name='Один товар',
        )

        result = merge_selected_main_products([product.id])

        self.assertIsNone(result)
