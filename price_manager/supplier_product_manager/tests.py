from io import BytesIO
from decimal import Decimal

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from supplier_manager.models import Currency, Supplier, Manufacturer
from supplier_product_manager.functions import load_setting
from supplier_product_manager.models import Link, Setting, SupplierFile, SupplierProduct


class BasicLoadTests(TestCase):
    def setUp(self):
        self.currency = Currency.objects.get(name="KZT")
        self.supplier = Supplier.objects.create(
            name="Test supplier",
            currency=self.currency,
            price_update_rate="Каждый день",
            stock_update_rate="Каждый день",
            delivery_days_available=1,
            delivery_days_navailable=3,
        )

    def _create_supplier_file(self, setting: Setting, dataframe: pd.DataFrame, filename: str = "supplier.xlsx"):
        setting.supplierfiles.all().delete()
        excel_buffer = BytesIO()
        dataframe.to_excel(excel_buffer, index=False)
        excel_buffer.seek(0)
        uploaded_file = SimpleUploadedFile(
            filename,
            excel_buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return SupplierFile.objects.create(setting=setting, file=uploaded_file)
    
    
    def _get_asserts_articlename(self, correct_values: list[dict]):
        res = []
        for row in correct_values:
            for attr in ['supplier_price', 'rrp', 'stock', 'manufacturer']:
                res.append((getattr(SupplierProduct.objects.get(supplier=self.supplier, article=row['article'], name=row['name']), attr), row[attr], row['article'] + attr))
        return res

    def test_basicupload_articlename(self):
        setting = Setting.objects.create(
            name="Загрузка артикул+имя",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена")
        Link.objects.create(setting=setting, key="rrp", value="РРЦ")
        Link.objects.create(setting=setting, key="stock", value="Остаток")
        Link.objects.create(setting=setting, key="manufacturer", value="Производитель")


        
        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Скидочная Цена":"1",  "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название": "Товар 2", "Цена": "2", "РРЦ":"2", "Скидочная Цена":"2",  "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Название": "Товар 3", "Цена": "3", "РРЦ":"3", "Скидочная Цена":"3",  "Остаток":"", "Производитель": "Производитель 3"},
                    {"Артикул": "А-4", "Название": "Товар 4", "Цена": "4", "РРЦ":"4", "Скидочная Цена":"",  "Остаток":"4", "Производитель": "Производитель 4"},
                    {"Артикул": "А-5", "Название": "Товар 5", "Цена": "5", "РРЦ":"", "Скидочная Цена":"5",  "Остаток":"5", "Производитель": "Производитель 5"},
                    {"Артикул": "А-6", "Название": "Товар 6", "Цена": "", "РРЦ":"6", "Скидочная Цена":"6",  "Остаток":"6", "Производитель": "Производитель 6"},
                    {"Артикул": "А-5", "Название": "Товар 5", "Цена": "6", "РРЦ":"6", "Скидочная Цена":"6",  "Остаток":"6", "Производитель": "Производитель 7"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":1, "discount_price":1, "stock":1, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 1")[0]},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":2, "discount_price":2, "stock":2, "manufacturer": None},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "discount_price":3, "stock":None, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 3")[0]},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 4, "rrp":4, "discount_price":None, "stock":4, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 4")[0]},
                {"article": "А-5", "name": "Товар 5", "supplier_price": 5, "rrp":None, "discount_price":5, "stock":5, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 5")[0]},
                {"article": "А-6", "name": "Товар 6", "supplier_price": None, "rrp":6, "discount_price":6, "stock":6, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 6")[0]},
            ]
        self._create_supplier_file(
            setting,
            uppload_df,
        )
        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 6)
        for product_value, correct_value, attr in self._get_asserts_articlename(correct_values):
            self.assertEqual(
                product_value,
                correct_value,
                attr
            )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNotNone(self.supplier.price_updated_at)

    def test_basicupload_article(self):
        setting = Setting.objects.create(
            name="Загрузка артикул",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена")
        Link.objects.create(setting=setting, key="rrp", value="РРЦ")
        Link.objects.create(setting=setting, key="stock", value="Остаток")
        Link.objects.create(setting=setting, key="manufacturer", value="Производитель")

        uppload_df_initial = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название": "Товар 2", "Цена": "2", "РРЦ":"2", "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Название": "Товар 3", "Цена": "3", "РРЦ":"3", "Остаток":"", "Производитель": "Производитель 3"},
                    {"Артикул": "А-4", "Название": "Товар 4", "Цена": "4", "РРЦ":"", "Остаток":"4", "Производитель": "Производитель 4"},
                    {"Артикул": "А-5", "Название": "Товар 5", "Цена": "", "РРЦ":"5", "Остаток":"5", "Производитель": "Производитель 5"},
                    {"Артикул": "А-5", "Название": "Товар 6", "Цена": "", "РРЦ":"6", "Остаток":"6", "Производитель": "Производитель 6"},
                ]
            )

        self._create_supplier_file(
            setting,
            uppload_df_initial,
        )
        load_setting(setting.pk)
        setting.create_new = False
        setting.save()
        namelink = Link.objects.get(setting=setting, key="name")
        namelink.value = None
        namelink.save()


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Цена": "2", "РРЦ":"2", "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Цена": "3", "РРЦ":"3", "Остаток":"", "Производитель": "Производитель 3"},
                    {"Артикул": "А-4", "Цена": "4", "РРЦ":"", "Остаток":"4", "Производитель": "Производитель 4"},
                    {"Артикул": "А-5", "Цена": "", "РРЦ":"5", "Остаток":"5", "Производитель": "Производитель 5"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":1, "stock":1, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 1")[0]},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":2, "stock":2, "manufacturer": None},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "stock":None, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 3")[0]},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 4, "rrp":None, "stock":4, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 4")[0]},
                {"article": "А-5", "name": "Товар 5", "supplier_price": None, "rrp":5, "stock":5, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 5")[0]},
                {"article": "А-5", "name": "Товар 6", "supplier_price": None, "rrp":5, "stock":5, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 5")[0]},
            ]
        

        self._create_supplier_file(
            setting,
            uppload_df,
        )
        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 6)
        for product_value, correct_value, attr in self._get_asserts_articlename(correct_values):
            self.assertEqual(
                product_value,
                correct_value,
                attr
            )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNotNone(self.supplier.price_updated_at)
    def test_uploadinitial_withvalue(self):
        setting = Setting.objects.create(
            name="Загрузка артикул+имя",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена", initial="100")
        Link.objects.create(setting=setting, key="rrp", value="РРЦ", initial="100")
        Link.objects.create(setting=setting, key="stock", value="Остаток", initial="100")
        Link.objects.create(setting=setting, key="manufacturer", value="Производитель", initial="Производитель 100")


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название": "Товар 2", "Цена": "2", "РРЦ":"2", "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Название": "Товар 3", "Цена": "3", "РРЦ":"3", "Остаток":"", "Производитель": "Производитель 3"},
                    {"Артикул": "А-4", "Название": "Товар 4", "Цена": "4", "РРЦ":"", "Остаток":"4", "Производитель": "Производитель 4"},
                    {"Артикул": "А-5", "Название": "Товар 5", "Цена": "", "РРЦ":"5", "Остаток":"5", "Производитель": "Производитель 5"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":1, "stock":1, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 1")[0]},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":2, "stock":2, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "stock":100, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 3")[0]},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 4, "rrp":100, "stock":4, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 4")[0]},
                {"article": "А-5", "name": "Товар 5", "supplier_price": 100, "rrp":5, "stock":5, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 5")[0]},
            ]
        self._create_supplier_file(
            setting,
            uppload_df,
        )
        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 5)
        for product_value, correct_value, attr in self._get_asserts_articlename(correct_values):
            self.assertEqual(
                product_value,
                correct_value,
                attr
            )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNotNone(self.supplier.price_updated_at)
    def test_uploadinitial_withoutvalue(self):
        setting = Setting.objects.create(
            name="Загрузка артикул+имя",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value=None, initial="100")
        Link.objects.create(setting=setting, key="rrp", value=None, initial="100")
        Link.objects.create(setting=setting, key="stock", value=None, initial="100")
        Link.objects.create(setting=setting, key="manufacturer", value=None, initial="Производитель 100")


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название": "Товар 2", "Цена": "2", "РРЦ":"2", "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Название": "Товар 3", "Цена": "3", "РРЦ":"3", "Остаток":"", "Производитель": "Производитель 3"},
                    {"Артикул": "А-4", "Название": "Товар 4", "Цена": "4", "РРЦ":"", "Остаток":"4", "Производитель": "Производитель 4"},
                    {"Артикул": "А-5", "Название": "Товар 5", "Цена": "", "РРЦ":"5", "Остаток":"5", "Производитель": "Производитель 5"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": 100, "rrp":100, "stock":100, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 100, "rrp":100, "stock":100, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 100, "rrp":100, "stock":100, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 100, "rrp":100, "stock":100, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
                {"article": "А-5", "name": "Товар 5", "supplier_price": 100, "rrp":100, "stock":100, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
            ]
        self._create_supplier_file(
            setting,
            uppload_df,
        )
        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 5)
        for product_value, correct_value, attr in self._get_asserts_articlename(correct_values):
            self.assertEqual(
                product_value,
                correct_value,
                attr
            )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNotNone(self.supplier.price_updated_at)
    def test_uploadnegvals(self):
        setting = Setting.objects.create(
            name="Загрузка артикул+имя",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена", initial="100")
        Link.objects.create(setting=setting, key="rrp", value="РРЦ", initial="100")
        Link.objects.create(setting=setting, key="stock", value="Остаток", initial="100")
        Link.objects.create(setting=setting, key="manufacturer", value="Производитель", initial="Производитель 100")


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "-1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название": "Товар 2", "Цена": "2", "РРЦ":"-2", "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Название": "Товар 3", "Цена": "3", "РРЦ":"3", "Остаток":"-3", "Производитель": "Производитель 3"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": None, "rrp":1, "stock":1, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 1")[0]},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":None, "stock":2, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 100")[0]},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "stock":None, "manufacturer": Manufacturer.objects.get_or_create(name="Производитель 3")[0]},
            ]
        self._create_supplier_file(
            setting,
            uppload_df,
        )
        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 3)
        for product_value, correct_value, attr in self._get_asserts_articlename(correct_values):
            self.assertEqual(
                product_value,
                correct_value,
                attr
            )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNotNone(self.supplier.price_updated_at)