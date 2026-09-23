from io import BytesIO
from decimal import Decimal
from unittest import mock

import pandas as pd
from django import forms
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from main_product_manager.models import MainProduct
from product.models import Product
from supplier_manager.models import Currency, Discount, Supplier
from supplier_product_manager.filters import SupplierProductFilter
from core.models import PersistentNotification
from supplier_product_manager.functions import (
    SupplierImportError,
    auto_detect_link_keys,
    get_sps,
    get_sps_result,
    get_df,
    get_df_sheet_names,
    load_setting,
)
from supplier_product_manager.models import ImportRun, Link, Setting, SupplierFile, SupplierProduct
from supplier_product_manager.tasks import (
    cleanup_supplier_files_task,
    copy_supplier_products_to_main_task,
    process_supplier_file_import,
)


class _PimUnreachable:
    """Заглушка для main_product_manager.utils.site: сеть в тестах запрещена.

    С Phase 2b ни импорт, ни копирование в ГП до PIM не доходят: связь с
    товаром ставится локально (link_to_local_products), а цепочка через
    search_vector удалена. Заглушка остаётся страховкой: любой будущий путь в
    сеть из этих тестов упрётся в неё, а не сходит в живой PIM. Громко — не
    обязательно: _fetch_pim_entity ловит Exception.
    Заглушка ставится в setUp, а не декоратором класса: @patch на классе
    оборачивает только те test_-методы, что видны в момент декорирования, и
    на базовом классе без собственных тестов не защищает ни одного наследника
    — на этом когда-то пять классов молча ходили в живой PIM.
    """

    def __getattr__(self, name):
        raise AssertionError(
            f'тест обратился к PIM: site.{name} — сеть в тестах запрещена'
        )


def _block_pim(testcase):
    """Отвязать тест от живого PIM на время одного test_-метода."""
    patcher = mock.patch('main_product_manager.utils.site', _PimUnreachable())
    patcher.start()
    testcase.addCleanup(patcher.stop)


class BasicLoadTests(TestCase):
    def setUp(self):
        _block_pim(self)
        self.currency, _ = Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})
        self.supplier = Supplier.objects.create(
            name="Test supplier",
            currency=self.currency,
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
            for attr in ['supplier_price', 'rrp', 'stock']:
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
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":1, "discount_price":1, "stock":1},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":2, "discount_price":2, "stock":2},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "discount_price":3, "stock":None},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 4, "rrp":4, "discount_price":None, "stock":4},
                {"article": "А-5", "name": "Товар 5", "supplier_price": 5, "rrp":None, "discount_price":5, "stock":5},
                {"article": "А-6", "name": "Товар 6", "supplier_price": None, "rrp":6, "discount_price":6, "stock":6},
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


    def test_link_to_a_dropped_column_is_ignored_not_a_crash(self):
        """Миграция 0010 удаляет сопоставления на category/manufacturer, но если
        такое переживёт её (или появится до неё), load_setting не должен
        передавать его в SupplierProduct(**data) — поля больше нет, и упал бы
        весь импорт прайса поставщика."""
        setting = Setting.objects.create(
            name="Устаревшее сопоставление",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена")
        Link.objects.create(setting=setting, key="manufacturer", value="Производитель")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "7", "Производитель": "Бренд"},
        ]))

        load_setting(setting.pk)

        row = SupplierProduct.objects.get(supplier=self.supplier, article="А-1")
        self.assertEqual(row.supplier_price, Decimal("7"))

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
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":1, "stock":1},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":2, "stock":2},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "stock":None},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 4, "rrp":None, "stock":4},
                {"article": "А-5", "name": "Товар 5", "supplier_price": None, "rrp":5, "stock":5},
                {"article": "А-5", "name": "Товар 6", "supplier_price": None, "rrp":5, "stock":5},
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
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":1, "stock":1},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":2, "stock":2},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "stock":100},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 4, "rrp":100, "stock":4},
                {"article": "А-5", "name": "Товар 5", "supplier_price": 100, "rrp":5, "stock":5},
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
                {"article": "А-1", "name": "Товар 1", "supplier_price": 100, "rrp":100, "stock":100},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 100, "rrp":100, "stock":100},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 100, "rrp":100, "stock":100},
                {"article": "А-4", "name": "Товар 4", "supplier_price": 100, "rrp":100, "stock":100},
                {"article": "А-5", "name": "Товар 5", "supplier_price": 100, "rrp":100, "stock":100},
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


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "-1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название": "Товар 2", "Цена": "2", "РРЦ":"-2", "Остаток":"2", "Производитель": ""},
                    {"Артикул": "А-3", "Название": "Товар 3", "Цена": "3", "РРЦ":"3", "Остаток":"-3", "Производитель": "Производитель 3"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": None, "rrp":1, "stock":1},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 2, "rrp":None, "stock":2},
                {"article": "А-3", "name": "Товар 3", "supplier_price": 3, "rrp":3, "stock":None},
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

    def test_ignorename_on_create(self):
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

        uppload_df_initial = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-1", "Название": "Товар 3", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                ]
            )

        self._create_supplier_file(
            setting,
            uppload_df_initial,
        )
        load_setting(setting.pk)
        setting.ignore_name = True
        setting.save()


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название":"Товар 2", "Цена": "0", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                    {"Артикул": "А-2", "Название":"Товар 2", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": 0, "rrp":1, "stock":1},
                {"article": "А-1", "name": "Товар 3", "supplier_price": 0, "rrp":1, "stock":1},
                {"article": "А-2", "name": "Товар 2", "supplier_price": 1, "rrp":1, "stock":1},
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
    def test_nulls_mapped_prices_and_stock_for_missing_rows(self):
        """A row absent from the new file is nulled, not zeroed, for the price
        and stock columns the setting still maps: the supplier gave no figure,
        and the raw layer records absence rather than inventing a synced 0.
        Consumers resolve that absence themselves - update_stocks() coalesces a
        NULL supplier stock to 0 because unknown stock is not sellable, and
        PriceTag.get_sprice() reads a NULL price as 0.

        The carve-out: fields the setting no longer maps are frozen at their
        last imported value, not cleared. supplier_price stays 1 here because
        its Link is deleted below.
        """
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

        uppload_df_initial = pd.DataFrame(
                [
                    {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                ]
            )

        self._create_supplier_file(
            setting,
            uppload_df_initial,
        )
        load_setting(setting.pk)
        Link.objects.get(setting=setting, key="supplier_price").delete()


        uppload_df = pd.DataFrame(
                [
                    {"Артикул": "А-2", "Название": "Товар 1", "Цена": "1", "РРЦ":"1", "Остаток":"1", "Производитель": "Производитель 1"},
                ]
            )
        
        correct_values = [
                {"article": "А-1", "name": "Товар 1", "supplier_price": 1, "rrp":None, "stock":None},
            ]
        

        self._create_supplier_file(
            setting,
            uppload_df,
        )
        result = load_setting(setting.pk)

        self.assertIsNotNone(result)
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 2)
        for product_value, correct_value, attr in self._get_asserts_articlename(correct_values):
            self.assertEqual(
                product_value,
                correct_value,
                attr
            )
        self.supplier.refresh_from_db()
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNotNone(self.supplier.price_updated_at)


@override_settings(DEBUG=False)
class GetSpsCacheTests(BasicLoadTests):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_get_sps_uses_cache_and_invalidates_on_setting_change(self):
        setting = Setting.objects.create(
            name="Кэширование sps",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=True,
        )
        Link.objects.create(setting=setting, key="article", value="Артикул")
        Link.objects.create(setting=setting, key="name", value="Название")
        Link.objects.create(setting=setting, key="supplier_price", value="Цена")

        self._create_supplier_file(
            setting,
            pd.DataFrame([{"Артикул": "А-1", "Название": "Товар 1", "Цена": "10"}]),
        )

        first_payload = get_sps(setting.pk)
        self.assertEqual(first_payload[0]["supplier_price"], 10.0)

        # Nothing changed, so the second call is served from cache and must not
        # re-read the spreadsheet.
        with mock.patch(
            "supplier_product_manager.functions.get_df",
            side_effect=AssertionError("get_df must not run on a cache hit"),
        ):
            cached_payload = get_sps(setting.pk)
        self.assertEqual(cached_payload, first_payload)

        # A new upload changes the signature, so the stale rows must not survive.
        self._create_supplier_file(
            setting,
            pd.DataFrame([{"Артикул": "А-1", "Название": "Товар 1", "Цена": "50"}]),
        )
        self.assertEqual(get_sps(setting.pk)[0]["supplier_price"], 50.0)

        price_link = Link.objects.get(setting=setting, key="supplier_price")
        price_link.value = None
        price_link.initial = "7"
        price_link.save()
        recached_payload = get_sps(setting.pk)
        self.assertEqual(recached_payload[0]["supplier_price"], 7.0)


class SupplierFileSelectionTests(TestCase):
    def setUp(self):
        self.currency, _ = Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})
        self.supplier = Supplier.objects.create(
            name="Test supplier for latest file",
            currency=self.currency,
            delivery_days_available=1,
            delivery_days_navailable=3,
        )

    def _create_supplier_file(
        self,
        setting: Setting,
        dataframe: pd.DataFrame,
        filename: str = "supplier.xlsx",
        sheet_name: str = "Sheet1",
        delete_existing: bool = True,
    ):
        if delete_existing:
            setting.supplierfiles.all().delete()
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
        excel_buffer.seek(0)
        uploaded_file = SimpleUploadedFile(
            filename,
            excel_buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return SupplierFile.objects.create(setting=setting, file=uploaded_file)

    def test_get_df_and_sheet_names_use_latest_supplier_file(self):
        setting = Setting.objects.create(
            name="Latest file selection",
            supplier=self.supplier,
            sheet_name="LatestSheet",
            create_new=True,
        )

        self._create_supplier_file(
            setting=setting,
            dataframe=pd.DataFrame([{"marker": "old"}]),
            filename="old_file.xlsx",
            sheet_name="OldSheet",
            delete_existing=False,
        )
        self._create_supplier_file(
            setting=setting,
            dataframe=pd.DataFrame([{"marker": "new"}]),
            filename="new_file.xlsx",
            sheet_name="LatestSheet",
            delete_existing=False,
        )

        df = get_df(setting.pk, recache=True)
        self.assertIsNotNone(df)
        self.assertEqual(df.iloc[0]["marker"], "new")

        sheet_names = get_df_sheet_names(setting.pk)
        self.assertEqual(sheet_names, ["LatestSheet"])


class AutoDetectLinkKeysTests(TestCase):
    def test_detects_standard_ru_columns(self):
        detected = auto_detect_link_keys(["Артикул", "Название", "Цена", "РРЦ", "Остаток"])
        self.assertEqual(
            detected,
            ["article", "name", "supplier_price", "rrp", "stock"],
        )

    def test_brand_and_category_columns_are_left_unmapped(self):
        """AUTO_LINK_ALIASES живёт отдельно от LINKS: оставь там «производитель»
        и «категория» — экран сопоставления пересоздавал бы ровно те Link,
        которые удаляет миграция 0010."""
        detected = auto_detect_link_keys(["Артикул", "Производитель", "Бренд", "Категория", "Группа"])
        self.assertEqual(detected, ["article", None, None, None, None])

    def test_does_not_duplicate_same_target_key(self):
        detected = auto_detect_link_keys(["Цена", "Цена со скидкой"])
        self.assertEqual(detected, ["supplier_price", "discount_price"])


class SupplierProductFilterTests(TestCase):
    def setUp(self):
        self.currency, _ = Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})
        self.supplier = Supplier.objects.create(
            name="Filter supplier",
            currency=self.currency,
            delivery_days_available=1,
            delivery_days_navailable=3,
        )
        self.discount_a = Discount.objects.create(name="Скидка A", supplier=self.supplier)
        self.discount_b = Discount.objects.create(name="Скидка B", supplier=self.supplier)

        SupplierProduct.objects.create(
            supplier=self.supplier,
            article="A1",
            name="Товар A1",
            discount=self.discount_a,
            updated_at=timezone.now(),
        )
        SupplierProduct.objects.create(
            supplier=self.supplier,
            article="B1",
            name="Товар B1",
            discount=self.discount_b,
            updated_at=timezone.now(),
        )

    def test_related_querysets_are_limited_by_other_filters(self):
        data = QueryDict("article=A1", mutable=True)
        filterset = SupplierProductFilter(
            data=data,
            queryset=SupplierProduct.objects.all(),
            pk=self.supplier.pk,
        )

        discount_ids = list(filterset.filters["discount"].field.queryset.values_list("pk", flat=True))

        self.assertEqual(discount_ids, [self.discount_a.pk])

    def test_category_and_manufacturer_filters_are_gone(self):
        """Колонки удалены в Phase 2b; фильтр по ним уронил бы страницу поставщика."""
        filterset = SupplierProductFilter(
            data=QueryDict("category=1&manufacturer=1", mutable=True),
            queryset=SupplierProduct.objects.all(),
            pk=self.supplier.pk,
        )

        self.assertNotIn("category", filterset.filters)
        self.assertNotIn("manufacturer", filterset.filters)
        self.assertEqual(filterset.qs.count(), 2)

    def test_filter_uses_checkbox_widgets_for_dict_filters(self):
        filterset = SupplierProductFilter(
            data=QueryDict("", mutable=True),
            queryset=SupplierProduct.objects.filter(supplier=self.supplier),
            pk=self.supplier.pk,
        )
        self.assertIsInstance(filterset.filters["discount"].field.widget, forms.CheckboxSelectMultiple)


class CopySupplierProductsToMainTaskTests(TestCase):
    """copy_supplier_products_to_main_task no longer matches MainProducts by
    (supplier, article, name) - MainProduct.main_product is now the identity,
    so every unlinked SupplierProduct must get its own MainProduct instead of
    being matched/merged into an existing one via that triple."""

    def setUp(self):
        _block_pim(self)
        self.currency, _ = Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})
        self.supplier = Supplier.objects.create(
            name="Copy task supplier",
            currency=self.currency,
            delivery_days_available=1,
            delivery_days_navailable=3,
        )
        self.user = get_user_model().objects.create_user(username="copytaskuser", password="p")

    def test_each_unlinked_supplier_product_gets_its_own_main_product(self):
        sp1 = SupplierProduct.objects.create(
            supplier=self.supplier, article="CT-1", name="Товар 1", description="Desc 1",
        )
        sp2 = SupplierProduct.objects.create(supplier=self.supplier, article="CT-2", name="Товар 2")

        result = copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        sp1.refresh_from_db()
        sp2.refresh_from_db()
        self.assertIsNotNone(sp1.main_product_id)
        self.assertIsNotNone(sp2.main_product_id)
        self.assertNotEqual(sp1.main_product_id, sp2.main_product_id)

        mp1 = MainProduct.objects.get(pk=sp1.main_product_id)
        self.assertEqual(mp1.article, "CT-1")
        self.assertEqual(mp1.name, "Товар 1")
        self.assertEqual(mp1.sku, "CT-1")

        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["updated_links_count"], 2)

    def test_new_row_is_linked_to_the_existing_product_with_its_sku(self):
        """Та тихая поломка, ради которой шаг и существует: до Phase 2b связь
        ставилась побочным эффектом пересборки search_vector. Без явного шага
        строка ложилась бы с product IS NULL — невидимой на /products/."""
        product = Product.objects.create(number="CT-5")
        sp = SupplierProduct.objects.create(supplier=self.supplier, article="CT-5", name="Товар 5")

        copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        sp.refresh_from_db()
        self.assertEqual(MainProduct.objects.get(pk=sp.main_product_id).product_id, product.pk)

    def test_copy_never_creates_a_product(self):
        """Создание Product — работа ночного reindex_pim_ids, не импорта."""
        SupplierProduct.objects.create(supplier=self.supplier, article="CT-6", name="Товар 6")

        copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        self.assertEqual(Product.objects.count(), 0)
        self.assertIsNone(MainProduct.objects.get(article="CT-6").product_id)

    def test_already_linked_row_gets_its_product_link_without_a_new_main_product(self):
        product = Product.objects.create(number="CT-3")
        mp = MainProduct.objects.create(supplier=self.supplier, article="CT-3", name="Товар 3", sku="CT-3")
        SupplierProduct.objects.create(
            supplier=self.supplier, article="CT-3", name="Товар 3", main_product=mp,
        )

        result = copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        mp.refresh_from_db()
        self.assertEqual(mp.product_id, product.pk)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["updated_links_count"], 0)
        self.assertEqual(MainProduct.objects.filter(supplier=self.supplier, article="CT-3").count(), 1)

    def test_running_task_twice_creates_nothing_the_second_time(self):
        sp = SupplierProduct.objects.create(supplier=self.supplier, article="CT-4", name="Товар 4")

        copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)
        second_result = copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        sp.refresh_from_db()
        self.assertEqual(MainProduct.objects.filter(article="CT-4").count(), 1)
        self.assertEqual(second_result["created_count"], 0)
        self.assertEqual(second_result["updated_links_count"], 0)


class MainProductLinkUniquenessTests(TestCase):
    """Regression guard for the core invariant this app's schema now
    enforces: at most one SupplierProduct may claim a given MainProduct."""

    def setUp(self):
        self.currency, _ = Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})
        self.supplier = Supplier.objects.create(
            name="Uniqueness supplier",
            currency=self.currency,
            delivery_days_available=1,
            delivery_days_navailable=3,
        )
        self.main_product = MainProduct.objects.create(
            supplier=self.supplier, article="U-1", name="Уникальный товар",
        )

    def test_second_supplier_product_cannot_claim_an_already_linked_main_product(self):
        SupplierProduct.objects.create(
            main_product=self.main_product, supplier=self.supplier, article="U-1", name="Товар",
        )
        other = SupplierProduct.objects.create(supplier=self.supplier, article="U-2", name="Другой товар")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                other.main_product = self.main_product
                other.save()

        other.refresh_from_db()
        self.assertIsNone(other.main_product_id)


def _xlsx_upload(sheets: dict[str, pd.DataFrame], filename: str = "supplier.xlsx") -> SimpleUploadedFile:
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        for sheet_name, dataframe in sheets.items():
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
    return SimpleUploadedFile(
        filename,
        excel_buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class _SupplierFixtureMixin:
    def _make_supplier(self, name="Поставщик для быстрых исправлений"):
        currency, _ = Currency.objects.get_or_create(name="KZT", defaults={"value": Decimal("1")})
        return Supplier.objects.create(
            name=name,
            currency=currency,
            delivery_days_available=1,
            delivery_days_navailable=3,
        )


@override_settings(DEBUG=False)
class GetDfSheetCacheTests(_SupplierFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.supplier = self._make_supplier()

    def test_switching_sheet_is_not_served_from_the_old_sheets_cache(self):
        setting = Setting.objects.create(name="Два листа", supplier=self.supplier, sheet_name="Первый")
        SupplierFile.objects.create(
            setting=setting,
            file=_xlsx_upload({
                "Первый": pd.DataFrame([{"marker": "first"}]),
                "Второй": pd.DataFrame([{"other": "second"}]),
            }),
        )
        self.assertEqual(list(get_df(setting.pk).columns), ["marker"])

        setting.sheet_name = "Второй"
        setting.save()
        self.assertEqual(list(get_df(setting.pk).columns), ["other"])


class UploadSupplierFileTests(_SupplierFixtureMixin, TestCase):
    def setUp(self):
        self.supplier = self._make_supplier()
        self.user = get_user_model().objects.create_user(username="uploader", password="x")
        self.client.force_login(self.user)
        self.url = reverse("supplier-upload", kwargs={"pk": self.supplier.pk})

    def test_unreadable_file_creates_no_setting(self):
        broken = SimpleUploadedFile("broken.xlsx", b"not a workbook", content_type="application/octet-stream")
        response = self.client.post(self.url, {"file": broken})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Setting.objects.filter(supplier=self.supplier).exists())
        self.assertFalse(SupplierFile.objects.exists())

    def test_name_clash_gets_numbered_setting(self):
        Setting.objects.create(name="price", supplier=self.supplier, sheet_name="Sheet1")
        upload = _xlsx_upload({"Sheet1": pd.DataFrame([{"Артикул": "А-1"}])}, "price.xlsx")
        self.client.post(self.url, {"file": upload})

        names = set(Setting.objects.filter(supplier=self.supplier).values_list("name", flat=True))
        self.assertEqual(names, {"price", "price(1)"})
        created = Setting.objects.get(supplier=self.supplier, name="price(1)")
        self.assertEqual(created.sheet_name, "Sheet1")
        self.assertEqual(created.supplierfiles.count(), 1)


class CleanupSupplierFilesTests(_SupplierFixtureMixin, TestCase):
    def setUp(self):
        self.supplier = self._make_supplier()
        self.setting = Setting.objects.create(name="Очистка", supplier=self.supplier, sheet_name="Sheet1")

    def _file(self, status):
        return SupplierFile.objects.create(
            setting=self.setting,
            status=status,
            file=_xlsx_upload({"Sheet1": pd.DataFrame([{"a": "1"}])}),
        )

    @override_settings(SUPPLIER_FILES_KEEP_LAST=0)
    def test_latest_file_survives_even_with_keep_last_zero(self):
        old = self._file(SupplierFile.STATUS_SUCCESS)
        latest = self._file(SupplierFile.STATUS_SUCCESS)

        cleanup_supplier_files_task()

        self.assertEqual(list(self.setting.supplierfiles.values_list("pk", flat=True)), [latest.pk])
        self.assertFalse(SupplierFile.objects.filter(pk=old.pk).exists())

    def test_queued_and_running_files_are_not_deleted(self):
        queued = self._file(SupplierFile.STATUS_QUEUED)
        running = self._file(SupplierFile.STATUS_RUNNING)
        latest = self._file(SupplierFile.STATUS_SUCCESS)

        cleanup_supplier_files_task()

        self.assertEqual(
            set(self.setting.supplierfiles.values_list("pk", flat=True)),
            {queued.pk, running.pk, latest.pk},
        )


class ImportRefusalReasonTests(TestCase):
    """Импорт, которому нечего загрузить, отказывает с причиной и ничего не меняет.

    Раньше get_sps молча возвращал None («обработано строк 0» без причины) или
    [] — и тогда load_setting падал с KeyError ['name'] на пустом DataFrame.
    Пустой результат, дошедший до обнуления пропавших строк, стёр бы остатки
    и цены всех товаров поставщика."""

    # Borrowed rather than inherited: subclassing BasicLoadTests would re-run
    # all of its tests a second time.
    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file

    def _setting(self, create_new=False, **links):
        setting = Setting.objects.create(
            name=f"Отказ {Setting.objects.count()}",
            supplier=self.supplier,
            sheet_name="Sheet1",
            create_new=create_new,
        )
        for key, value in links.items():
            Link.objects.create(setting=setting, key=key, value=value)
        return setting

    def _existing(self):
        return SupplierProduct.objects.create(
            supplier=self.supplier, article="СТАРЫЙ-1", name="Старый товар",
            stock=7, supplier_price=Decimal("100"),
        )

    def test_no_matching_rows_is_a_reason_not_a_keyerror_and_keeps_existing_data(self):
        existing = self._existing()
        setting = self._setting(article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "НОВЫЙ-1", "Название": "Новый", "Остаток": "3"}]),
        )

        with self.assertRaisesMessage(SupplierImportError, "не совпала с товарами поставщика"):
            load_setting(setting.pk)

        existing.refresh_from_db()
        self.assertEqual(existing.stock, 7)
        self.assertEqual(existing.supplier_price, Decimal("100"))

    def test_missing_article_column_names_it_and_lists_file_columns(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название")
        self._create_supplier_file(setting, pd.DataFrame([{"Код": "А-1", "Название": "Товар"}]))

        with self.assertRaisesMessage(SupplierImportError, "нет столбца артикула «Артикул»"):
            get_sps(setting.pk)
        with self.assertRaisesMessage(SupplierImportError, "«Код»"):
            get_sps(setting.pk)

    def test_create_new_without_name_column(self):
        setting = self._setting(create_new=True, article="Артикул", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1", "Остаток": "1"}]))

        with self.assertRaisesMessage(SupplierImportError, "нужен столбец названия"):
            get_sps(setting.pk)

    def test_rows_without_any_value(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар", "Остаток": "нет данных"}]),
        )

        with self.assertRaisesMessage(SupplierImportError, "ни в одной нет значений"):
            get_sps(setting.pk)

    def test_no_file_and_no_links(self):
        setting = self._setting(create_new=True)
        with self.assertRaisesMessage(SupplierImportError, "не загружен файл"):
            get_sps(setting.pk)

        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1"}]))
        with self.assertRaisesMessage(SupplierImportError, "Не сопоставлен ни один столбец"):
            get_sps(setting.pk)

    def test_mapped_column_missing_from_file_falls_back_to_initial(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название")
        Link.objects.create(setting=setting, key="stock", value="Остаток", initial="5")
        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар"}]))

        load_setting(setting.pk)

        self.assertEqual(SupplierProduct.objects.get(supplier=self.supplier, article="А-1").stock, 5)

    def test_task_reports_reason_and_does_not_raise(self):
        existing = self._existing()
        setting = self._setting(article="Артикул", name="Название", stock="Остаток")
        supplier_file = self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "НОВЫЙ-1", "Название": "Новый", "Остаток": "3"}]),
        )
        user = get_user_model().objects.create_user(username="importer", password="x")

        result = process_supplier_file_import(setting.pk, user.pk)

        self.assertEqual(result["status"], "error")
        self.assertIn("Причина: Ни одна из 1 строк", result["message"])
        supplier_file.refresh_from_db()
        self.assertEqual(supplier_file.status, SupplierFile.STATUS_ERROR)
        self.assertIn("не совпала", supplier_file.logs)
        notification = PersistentNotification.objects.get(user=user)
        self.assertEqual(notification.level, "danger")
        self.assertIn("данные не изменены", notification.message)
        existing.refresh_from_db()
        self.assertEqual(existing.stock, 7)


class ImportStatsTests(TestCase):
    """Счётчики разбора и применения — основа истории покрытия настройки."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def test_parse_counters_by_stage(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Товар 1")
        SupplierProduct.objects.create(supplier=self.supplier, article="А-2", name="Товар 2")
        SupplierProduct.objects.create(supplier=self.supplier, article="А-3", name="Товар 3")
        setting = self._setting(article="Артикул", name="Название", supplier_price="Цена", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "10", "Остаток": "5"},
            {"Артикул": "А-2", "Название": "Товар 2", "Цена": "20", "Остаток": "нет"},
            {"Артикул": "А-3", "Название": "Товар 3", "Цена": "н/д", "Остаток": "н/д"},   # нет значений
            {"Артикул": "", "Название": "Итого", "Цена": "30", "Остаток": "3"},         # нет артикула
            {"Артикул": "Б-9", "Название": "Чужой", "Цена": "40", "Остаток": "4"},      # нет в базе
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "11", "Остаток": "6"},    # дубликат
        ]))

        _, stats = get_sps_result(setting.pk)

        self.assertEqual(stats["rows_in_sheet"], 6)
        self.assertEqual(stats["rows_with_article"], 5)
        self.assertEqual(stats["rows_with_values"], 4)
        self.assertEqual(stats["rows_unmatched"], 1)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["covered"], 2)
        self.assertEqual(stats["covered_price"], 2)
        self.assertEqual(stats["covered_stock"], 1)
        self.assertEqual(stats["mapped_keys"], ["article", "name", "stock", "supplier_price"])

    def test_unmapped_stock_counts_as_zero_stock_coverage(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", supplier_price="Цена")
        self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар", "Цена": "10", "Остаток": "5"}]),
        )

        _, stats = get_sps_result(setting.pk)

        self.assertEqual((stats["covered"], stats["covered_price"], stats["covered_stock"]), (1, 1, 0))

    @override_settings(DEBUG=False)
    def test_stats_are_served_from_cache_with_payload(self):
        cache.clear()
        self.addCleanup(cache.clear)
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар", "Остаток": "5"}]))
        first = get_sps_result(setting.pk)

        with mock.patch("supplier_product_manager.functions.get_df",
                        side_effect=AssertionError("get_df must not run on a cache hit")):
            self.assertEqual(get_sps_result(setting.pk), first)
            self.assertEqual(get_sps(setting.pk), first[0])

    def test_load_setting_reports_created_updated_missing(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Товар 1", stock=1)
        SupplierProduct.objects.create(supplier=self.supplier, article="СТАРЫЙ", name="Старый", stock=9)
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Остаток": "2"},
            {"Артикул": "А-2", "Название": "Товар 2", "Остаток": "3"},
        ]))

        outcome = load_setting(setting.pk)

        self.assertEqual(len(outcome.sps), 2)
        self.assertEqual(
            (outcome.stats["created"], outcome.stats["updated"], outcome.stats["missing"]), (1, 1, 1),
        )


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class ImportRunRecordingTests(TestCase):
    """Каждый запуск задачи импорта оставляет ImportRun — применённый, отказ или ошибка.

    Проверка импорта здесь выключена (история не требуется) — она покрыта
    ImportGuardTests."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def _user(self):
        return get_user_model().objects.create_user(username=f"run-{ImportRun.objects.count()}", password="x")

    def test_applied_run_records_counters(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название",
                                supplier_price="Цена", stock="Остаток")
        supplier_file = self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "10", "Остаток": "5"},
            {"Артикул": "А-2", "Название": "Товар 2", "Цена": "20", "Остаток": ""},
        ]))
        user = self._user()

        result = process_supplier_file_import(setting.pk, user.pk)

        self.assertEqual(result["status"], "ok")
        run = ImportRun.objects.get(setting=setting)
        self.assertEqual(run.status, ImportRun.STATUS_APPLIED)
        self.assertEqual((run.supplier_id, run.supplier_file_id, run.user_id),
                         (self.supplier.pk, supplier_file.pk, user.pk))
        self.assertEqual(run.file_name, supplier_file.file.name)
        self.assertEqual((run.covered, run.covered_price, run.covered_stock), (2, 2, 1))
        self.assertEqual((run.created, run.updated, run.missing), (2, 0, 0))
        self.assertEqual(run.mapped_keys, ["article", "name", "stock", "supplier_price"])
        self.assertIsNotNone(run.finished_at)
        self.assertIn("с ценой 2, с остатком 1", result["message"])

    def test_refused_run_keeps_reason_and_parse_counters(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="СТАРЫЙ", name="Старый")
        setting = self._setting(article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "НОВЫЙ", "Название": "Новый", "Остаток": "3"}]),
        )

        process_supplier_file_import(setting.pk, self._user().pk)

        run = ImportRun.objects.get(setting=setting)
        self.assertEqual(run.status, ImportRun.STATUS_REFUSED)
        self.assertIn("не совпала", run.message)
        self.assertEqual((run.rows_with_values, run.rows_unmatched, run.covered), (1, 1, 0))
        self.assertIsNone(run.created)

    def test_failed_run_is_recorded_and_reraised(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар", "Остаток": "1"}]),
        )

        with mock.patch("supplier_product_manager.tasks.load_setting", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                process_supplier_file_import(setting.pk, self._user().pk)

        run = ImportRun.objects.get(setting=setting)
        self.assertEqual((run.status, run.message), (ImportRun.STATUS_FAILED, "boom"))

    def test_run_outlives_its_file(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        supplier_file = self._create_supplier_file(
            setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар", "Остаток": "1"}]),
        )
        process_supplier_file_import(setting.pk, self._user().pk)

        supplier_file.delete()

        run = ImportRun.objects.get(setting=setting)
        self.assertIsNone(run.supplier_file_id)
        self.assertTrue(run.file_name)


@override_settings(SUPPLIER_IMPORT_GUARD_RATIO=0.7, SUPPLIER_IMPORT_GUARD_WINDOW=5,
                   SUPPLIER_IMPORT_GUARD_MIN_HISTORY=3)
class ImportGuardTests(TestCase):
    """Файл, покрывающий заметно меньше обычного, не применяется, а ждёт подтверждения."""

    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def setUp(self):
        BasicLoadTests.setUp(self)
        self.user = get_user_model().objects.create_user(username="guard", password="x")
        self.client.force_login(self.user)
        self.existing = SupplierProduct.objects.create(
            supplier=self.supplier, article="СТАРЫЙ", name="Старый", stock=7, supplier_price=Decimal("100"),
        )
        self.setting = self._setting(create_new=True, article="Артикул", name="Название",
                                     supplier_price="Цена", stock="Остаток")

    def _history(self, *pairs):
        """Применённые импорты настройки: пары (covered_price, covered_stock), от старых к новым."""
        for price, stock in pairs:
            ImportRun.objects.create(setting=self.setting, supplier=self.supplier,
                                     status=ImportRun.STATUS_APPLIED,
                                     covered_price=price, covered_stock=stock)

    def _file(self, rows):
        return self._create_supplier_file(self.setting, pd.DataFrame([
            {"Артикул": f"А-{i}", "Название": f"Товар {i}", "Цена": price, "Остаток": stock}
            for i, (price, stock) in enumerate(rows)
        ]))

    def _import(self):
        return process_supplier_file_import(self.setting.pk, self.user.pk)

    def _assert_data_unchanged(self):
        self.existing.refresh_from_db()
        self.assertEqual((self.existing.stock, self.existing.supplier_price), (7, Decimal("100")))
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 1)

    # --- the check ---------------------------------------------------------

    def test_first_imports_wait_for_confirmation_until_history_accumulates(self):
        self._history((2, 2), (2, 2))
        supplier_file = self._file([("10", "1"), ("20", "2")])

        result = self._import()

        self.assertEqual(result["status"], "needs_confirmation")
        run = ImportRun.objects.get(pk=result["run_id"])
        self.assertEqual(run.status, ImportRun.STATUS_NEEDS_CONFIRMATION)
        self.assertEqual(run.guard_reasons, [{"kind": "history", "have": 2, "need": 3}])
        self.assertEqual((run.covered, run.created, run.missing), (2, 2, 1))
        self._assert_data_unchanged()
        supplier_file.refresh_from_db()
        self.assertEqual(supplier_file.status, SupplierFile.STATUS_NEEDS_CONFIRMATION)
        notification = PersistentNotification.objects.get(user=self.user)
        self.assertEqual(notification.level, "warning")
        self.assertIn("история ещё копится (2 из 3)", notification.message)
        self.assertEqual(notification.link, f"/supplier/{self.supplier.pk}/?import_run={run.pk}#settings")

    def test_usual_file_is_applied(self):
        self._history((2, 2), (2, 2), (2, 2))
        self._file([("10", "1"), ("20", "2")])

        self.assertEqual(self._import()["status"], "ok")
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 3)

    def test_price_coverage_drop_waits(self):
        self._history((4, 0), (4, 0), (4, 0))
        self._file([("10", "1"), ("н/д", "2"), ("н/д", "3"), ("н/д", "4")])

        result = self._import()

        run = ImportRun.objects.get(pk=result["run_id"])
        self.assertEqual(run.guard_reasons, [
            {"kind": "drop", "metric": "covered_price", "value": 1, "baseline": 4},
        ])
        self.assertEqual(run.reason_lines(), ["С ценой: 1 строка, обычно ~4"])
        self._assert_data_unchanged()

    def test_stock_coverage_drop_waits_while_prices_look_normal(self):
        self._history((3, 3), (3, 3), (3, 3))
        self._file([("10", "нет"), ("20", "нет"), ("30", "нет")])

        result = self._import()

        run = ImportRun.objects.get(pk=result["run_id"])
        self.assertEqual([r["metric"] for r in run.guard_reasons], ["covered_stock"])

    def test_metric_the_setting_never_delivered_is_not_checked(self):
        self._history((3, 0), (3, 0), (3, 0))
        self._file([("10", ""), ("20", ""), ("30", "")])

        self.assertEqual(self._import()["status"], "ok")

    def test_one_outlier_does_not_move_the_median(self):
        from supplier_product_manager import guard
        self._history((100, 0), (100, 0), (5, 0), (100, 0), (100, 0))

        self.assertTrue(guard.evaluate(self.setting, {"covered_price": 90, "covered_stock": 0}).ok)
        self.assertFalse(guard.evaluate(self.setting, {"covered_price": 60, "covered_stock": 0}).ok)

    def test_new_import_supersedes_an_unconfirmed_one(self):
        self._file([("10", "1")])
        first = self._import()["run_id"]

        self._import()

        self.assertEqual(ImportRun.objects.get(pk=first).status, ImportRun.STATUS_SUPERSEDED)

    # --- confirmation ------------------------------------------------------

    def _pending_run(self):
        self._file([("10", "1"), ("20", "2")])
        return ImportRun.objects.get(pk=self._import()["run_id"])

    def test_apply_view_claims_the_run_once_and_dispatches_it(self):
        run = self._pending_run()
        url = reverse("import-run-apply", kwargs={"pk": run.pk})

        with mock.patch("supplier_product_manager.views.process_supplier_file_import") as task:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url)

        task.delay.assert_called_once_with(self.setting.pk, self.user.pk, confirmed_run_id=run.pk)
        run.refresh_from_db()
        self.assertEqual((run.status, run.confirmed_by_id), (ImportRun.STATUS_RUNNING, self.user.pk))
        self.assertIsNotNone(run.confirmed_at)

    def test_confirmed_run_applies_without_a_second_check(self):
        run = self._pending_run()
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.STATUS_RUNNING, confirmed_by=self.user)

        result = process_supplier_file_import(self.setting.pk, self.user.pk, confirmed_run_id=run.pk)

        self.assertEqual(result["status"], "ok")
        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.STATUS_APPLIED)
        self.assertEqual(run.guard_reasons, [{"kind": "history", "have": 0, "need": 3}])
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 3)
        self.existing.refresh_from_db()
        self.assertIsNone(self.existing.stock)

    def test_confirmation_is_refused_when_the_mapping_changed_meanwhile(self):
        run = self._pending_run()
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.STATUS_RUNNING)
        Link.objects.filter(setting=self.setting, key="stock").update(value="Склад")

        result = process_supplier_file_import(self.setting.pk, self.user.pk, confirmed_run_id=run.pk)

        self.assertEqual(result["status"], "superseded")
        self.assertEqual(ImportRun.objects.get(pk=run.pk).status, ImportRun.STATUS_SUPERSEDED)
        self._assert_data_unchanged()

    def test_cancel_view(self):
        run = self._pending_run()

        self.client.post(reverse("import-run-cancel", kwargs={"pk": run.pk}))

        run.refresh_from_db()
        self.assertEqual(run.status, ImportRun.STATUS_CANCELLED)
        self.assertEqual(run.supplier_file.status, SupplierFile.STATUS_ERROR)
        self._assert_data_unchanged()

    def test_new_upload_supersedes_an_unconfirmed_run(self):
        run = self._pending_run()
        excel = BytesIO()
        pd.DataFrame([{"Артикул": "А-1", "Название": "Товар"}]).to_excel(excel, index=False)
        upload = SimpleUploadedFile("new.xlsx", excel.getvalue())

        self.client.post(reverse("supplier-upload", kwargs={"pk": self.supplier.pk}),
                         {"file": upload, "setting": self.setting.pk})

        self.assertEqual(ImportRun.objects.get(pk=run.pk).status, ImportRun.STATUS_SUPERSEDED)

    def test_cleanup_keeps_a_file_waiting_for_confirmation(self):
        run = self._pending_run()
        SupplierFile.objects.create(
            setting=self.setting, status=SupplierFile.STATUS_SUCCESS,
            file=SimpleUploadedFile("newer.xlsx", b"x"),
        )

        cleanup_supplier_files_task()

        self.assertTrue(SupplierFile.objects.filter(pk=run.supplier_file_id).exists())

    # --- screens -----------------------------------------------------------

    def test_confirm_modal_shows_reasons_figures_and_actions(self):
        run = self._pending_run()

        response = self.client.get(reverse("import-run-confirm", kwargs={"pk": run.pk}))

        self.assertContains(response, "история ещё копится (0 из 3)")
        self.assertContains(response, "нет в файле — обнулятся")
        self.assertContains(response, reverse("import-run-apply", kwargs={"pk": run.pk}))
        self.assertContains(response, reverse("import-run-cancel", kwargs={"pk": run.pk}))

    def test_confirm_modal_of_a_processed_run_has_no_actions(self):
        run = self._pending_run()
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.STATUS_CANCELLED)

        response = self.client.get(reverse("import-run-confirm", kwargs={"pk": run.pk}))

        self.assertContains(response, "уже обработан: отменён")
        self.assertNotContains(response, reverse("import-run-apply", kwargs={"pk": run.pk}))

    def test_notification_link_opens_the_dialog_only_while_pending(self):
        run = self._pending_run()
        url = f"{reverse('supplier-detail', kwargs={'pk': self.supplier.pk})}?import_run={run.pk}"

        self.assertEqual(self.client.get(url).context["import_confirm_url"],
                         reverse("import-run-confirm", kwargs={"pk": run.pk}))
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.STATUS_APPLIED)
        self.assertNotIn("import_confirm_url", self.client.get(url).context)

    def test_settings_table_shows_last_import(self):
        run = self._pending_run()

        response = self.client.get(reverse("settings", kwargs={"pk": self.supplier.pk}))

        self.assertContains(response, "Ждёт подтверждения")
        self.assertContains(response, reverse("import-run-confirm", kwargs={"pk": run.pk}))

    # --- atomic apply ------------------------------------------------------

    @override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
    def test_failed_apply_leaves_no_partial_writes(self):
        self._file([("10", "1"), ("20", "2")])

        with mock.patch("supplier_manager.models.Supplier.save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._import()

        self._assert_data_unchanged()
