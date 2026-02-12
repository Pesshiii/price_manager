from io import BytesIO
from decimal import Decimal

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from supplier_manager.models import Currency, Supplier
from supplier_product_manager.functions import load_setting
from supplier_product_manager.models import Link, Setting, SupplierFile, SupplierProduct


class LoadSettingTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.create(name="KZT", value=Decimal("1"))
        self.supplier = Supplier.objects.create(
            name="Test supplier",
            currency=self.currency,
            price_update_rate="Каждый день",
            stock_update_rate="Каждый день",
            delivery_days_available=1,
            delivery_days_navailable=3,
        )

    def _create_supplier_file(self, setting: Setting, dataframe: pd.DataFrame, filename: str = "supplier.xlsx"):
        excel_buffer = BytesIO()
        dataframe.to_excel(excel_buffer, index=False)
        excel_buffer.seek(0)
        uploaded_file = SimpleUploadedFile(
            filename,
            excel_buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return SupplierFile.objects.create(setting=setting, file=uploaded_file)

    def test_load_setting_imports_products_from_supplier_file(self):
        setting = Setting.objects.create(
            name="Основная загрузка",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена")

        self._create_supplier_file(
            setting,
            pd.DataFrame(
                [
                    {"Артикул": "A-1", "Название": "Товар 1", "Цена": "123.45"},
                    {"Артикул": "A-2", "Название": "Товар 2", "Цена": "50"},
                ]
            ),
        )

        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 2)
        self.assertEqual(
            SupplierProduct.objects.get(supplier=self.supplier, article="A-1", name="Товар 1").supplier_price,
            Decimal("123.45"),
        )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.price_updated_at)
