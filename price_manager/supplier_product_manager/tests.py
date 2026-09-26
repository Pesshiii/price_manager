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

    def test_match_by_article_writes_into_all_existing_rows_of_an_article(self):
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
        # Was ignore_name: an article already in the database takes the data
        # into all its existing rows, names untouched.
        setting.match_by_article = True
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
        NULL supplier stock to 0 because unknown stock is not sellable, and the
        price rules clear prices computed from a NULL price
        (product_price_manager.clear_unsourced_prices).

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

    def test_copy_creates_the_product_a_new_sku_has_none_of(self):
        """Строка ГП без товара не бывает: товар создаётся сразу, а не ночью."""
        SupplierProduct.objects.create(supplier=self.supplier, article="CT-6", name="Товар 6")

        copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        row = MainProduct.objects.get(article="CT-6")
        self.assertIsNotNone(row.product_id)
        self.assertEqual((row.product.number, row.product.name), ("CT-6", "Товар 6"))

    def test_copy_links_case_insensitively_and_leaves_other_rows_alone(self):
        product = Product.objects.create(number="ct-7")
        stranger = MainProduct.objects.create(supplier=self.supplier, article="X", name="Чужая", sku="OTHER-1")
        sp = SupplierProduct.objects.create(supplier=self.supplier, article="CT-7", name="Товар 7")

        copy_supplier_products_to_main_task(self.supplier.id, None, self.user.id)

        sp.refresh_from_db()
        self.assertEqual(MainProduct.objects.get(pk=sp.main_product_id).product_id, product.pk)
        stranger.refresh_from_db()
        self.assertIsNone(stranger.product_id)

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
        old = SupplierProduct.objects.create(supplier=self.supplier, article="СТАРЫЙ", name="Старый", stock=9)
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        old.source_settings.add(setting)  # loaded by an earlier import of this setting
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
        # As if loaded by an earlier import of this setting: only such rows are
        # cleared when they vanish from its file.
        self.existing.source_settings.add(self.setting)

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

    # --- the confirmation notification --------------------------------------

    def _confirmations(self, run):
        return PersistentNotification.objects.filter(kind="confirmation", ref=f"import_run:{run.pk}")

    def test_confirmation_notification_does_not_expire(self):
        run = self._pending_run()
        notification = self._confirmations(run).get()

        PersistentNotification.objects.mark_seen([notification.pk])

        notification.refresh_from_db()
        self.assertIsNone(notification.expires_at)

    def test_apply_dismisses_the_confirmation_for_everyone(self):
        run = self._pending_run()
        other = get_user_model().objects.create_user(username="colleague", password="x")
        self.client.force_login(other)

        with mock.patch("supplier_product_manager.views.process_supplier_file_import"):
            self.client.post(reverse("import-run-apply", kwargs={"pk": run.pk}))

        self.assertFalse(self._confirmations(run).exists())

    def test_cancel_dismisses_the_confirmation(self):
        run = self._pending_run()

        self.client.post(reverse("import-run-cancel", kwargs={"pk": run.pk}))

        self.assertFalse(self._confirmations(run).exists())

    def test_new_import_dismisses_the_superseded_confirmation(self):
        run = self._pending_run()

        self._import()

        self.assertFalse(self._confirmations(run).exists())

    def test_new_upload_dismisses_the_superseded_confirmation(self):
        run = self._pending_run()
        excel = BytesIO()
        pd.DataFrame([{"Артикул": "А-1", "Название": "Товар"}]).to_excel(excel, index=False)

        self.client.post(reverse("supplier-upload", kwargs={"pk": self.supplier.pk}),
                         {"file": SimpleUploadedFile("new.xlsx", excel.getvalue()), "setting": self.setting.pk})

        self.assertFalse(self._confirmations(run).exists())

    def test_refused_confirmation_dismisses_the_notification(self):
        run = self._pending_run()
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.STATUS_RUNNING)
        Link.objects.filter(setting=self.setting, key="stock").update(value="Склад")

        process_supplier_file_import(self.setting.pk, self.user.pk, confirmed_run_id=run.pk)

        self.assertFalse(self._confirmations(run).exists())

    def test_cleanup_drops_confirmations_of_runs_no_longer_pending(self):
        run = self._pending_run()
        ImportRun.objects.filter(pk=run.pk).update(status=ImportRun.STATUS_APPLIED)

        cleanup_supplier_files_task()

        self.assertFalse(self._confirmations(run).exists())

    def test_cleanup_keeps_a_pending_confirmation(self):
        run = self._pending_run()

        cleanup_supplier_files_task()

        self.assertTrue(self._confirmations(run).exists())

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

        with mock.patch("supplier_product_manager.functions._stamp_supplier", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._import()

        self._assert_data_unchanged()


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class DuplicateWarningTests(TestCase):
    """Повторы строк и артикулы с разными названиями не останавливают импорт,
    но о них предупреждают."""

    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def setUp(self):
        BasicLoadTests.setUp(self)
        self.user = get_user_model().objects.create_user(username="dups", password="x")

    def _messy_file(self, setting):
        return self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Кабель 1 м", "Остаток": "1"},
            {"Артикул": "А-1", "Название": "Кабель 2 м", "Остаток": "2"},   # артикул с другим названием
            {"Артикул": "Б-2", "Название": "Розетка", "Остаток": "3"},
            {"Артикул": "Б-2", "Название": "Розетка", "Остаток": "9"},      # точный повтор
            {"Артикул": "В-3", "Название": "Выключатель", "Остаток": "4"},
        ]))

    def test_counters(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._messy_file(setting)

        _, stats = get_sps_result(setting.pk)

        self.assertEqual(stats["article_conflicts"], 1)
        self.assertEqual(stats["article_conflict_examples"], ["А-1"])
        self.assertEqual(stats["duplicates"], 1)

    def test_import_applies_everything_and_warns(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._messy_file(setting)

        result = process_supplier_file_import(setting.pk, self.user.pk)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier, article="А-1").count(), 2)
        self.assertEqual(SupplierProduct.objects.get(supplier=self.supplier, article="Б-2").stock, 3)
        notification = PersistentNotification.objects.get(user=self.user)
        self.assertEqual(notification.level, "warning")
        self.assertIn("повторов строк: 1 (взята первая из повторяющихся)", notification.message)
        self.assertIn("артикулов с разными названиями: 1 (например: А-1)", notification.message)
        run = ImportRun.objects.get(setting=setting)
        self.assertEqual((run.duplicates, run.article_conflicts), (1, 1))

    def test_clean_file_reports_success_without_warning(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Кабель", "Остаток": "1"},
        ]))

        process_supplier_file_import(setting.pk, self.user.pk)

        notification = PersistentNotification.objects.get(user=self.user)
        self.assertEqual(notification.level, "success")
        self.assertNotIn("Внимание", notification.message)

    def test_names_taken_from_the_database_are_not_a_file_conflict(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Кабель 1 м")
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Кабель 2 м")
        setting = self._setting(article="Артикул", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1", "Остаток": "5"}]))

        _, stats = get_sps_result(setting.pk)

        self.assertEqual(stats["article_conflicts"], 0)
        self.assertEqual(stats["covered"], 2)


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class MatchByArticleTests(TestCase):
    """Setting.match_by_article: товар определяется одним артикулом."""

    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def setUp(self):
        BasicLoadTests.setUp(self)
        self.user = get_user_model().objects.create_user(username="by-article", password="x")

    def _by_article(self, create_new=True, **links):
        setting = self._setting(create_new=create_new, **(links or
                                {"article": "Артикул", "name": "Название", "stock": "Остаток"}))
        setting.match_by_article = True
        setting.save()
        return setting

    def _import(self, setting):
        return process_supplier_file_import(setting.pk, self.user.pk)

    def test_new_name_renames_the_row_and_keeps_its_link(self):
        mp = MainProduct.objects.create(supplier=self.supplier, article="А-1", name="Старое")
        sp = SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Старое",
                                            main_product=mp, stock=1)
        setting = self._by_article()
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Новое", "Остаток": "5"},
        ]))

        result = self._import(setting)

        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier).count(), 1)
        sp.refresh_from_db()
        self.assertEqual((sp.name, sp.stock, sp.main_product_id), ("Новое", 5, mp.pk))
        run = ImportRun.objects.get(setting=setting)
        self.assertEqual((run.renamed, run.created, run.updated, run.missing), (1, 0, 1, 0))
        self.assertIn("переименовано 1", result["message"])

    def test_repeated_article_in_file_takes_the_first_row_and_warns(self):
        setting = self._by_article()
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Кабель 1 м", "Остаток": "1"},
            {"Артикул": "А-1", "Название": "Кабель 2 м", "Остаток": "2"},
        ]))

        self._import(setting)

        row = SupplierProduct.objects.get(supplier=self.supplier, article="А-1")
        self.assertEqual((row.name, row.stock), ("Кабель 1 м", 1))
        message = PersistentNotification.objects.get(user=self.user).message
        self.assertIn("повторов строк: 1", message)
        self.assertIn("артикулов с разными названиями: 1 (например: А-1) — взята первая строка", message)

    def test_several_existing_rows_of_an_article_all_get_the_data_and_are_reported(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Вариант 1", stock=1)
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Вариант 2", stock=1)
        setting = self._by_article()
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Что-то третье", "Остаток": "7"},
        ]))

        self._import(setting)

        rows = SupplierProduct.objects.filter(supplier=self.supplier).order_by("name")
        self.assertEqual([(r.name, r.stock) for r in rows], [("Вариант 1", 7), ("Вариант 2", 7)])
        message = PersistentNotification.objects.get(user=self.user).message
        self.assertIn("у которых в базе несколько товаров: 1 (например: А-1) — данные записаны во все", message)

    def test_without_create_new_unknown_articles_do_not_match(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Старое", stock=1)
        setting = self._by_article(create_new=False)
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Новое", "Остаток": "3"},
            {"Артикул": "Б-2", "Название": "Чужой", "Остаток": "4"},
        ]))

        _, stats = get_sps_result(setting.pk)
        self._import(setting)

        self.assertEqual((stats["rows_unmatched"], stats["renamed"], stats["covered"]), (1, 1, 1))
        self.assertEqual(list(SupplierProduct.objects.filter(supplier=self.supplier)
                              .values_list("article", "name", "stock")), [("А-1", "Новое", 3)])

    def test_without_a_name_column_the_existing_name_is_kept(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Старое", stock=1)
        setting = self._by_article(create_new=False, article="Артикул", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1", "Остаток": "9"}]))

        self._import(setting)

        row = SupplierProduct.objects.get(supplier=self.supplier)
        self.assertEqual((row.name, row.stock), ("Старое", 9))

    def test_default_mode_keeps_variants_as_separate_products(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Кабель 1 м", "Остаток": "1"},
            {"Артикул": "А-1", "Название": "Кабель 2 м", "Остаток": "2"},
        ]))

        self._import(setting)

        self.assertEqual(SupplierProduct.objects.filter(supplier=self.supplier, article="А-1").count(), 2)


class SettingOwnedRowsTests(TestCase):
    """Импорт очищает только строки своей настройки и только поля, которые она сопоставляет."""

    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def setUp(self):
        BasicLoadTests.setUp(self)
        self.warehouse_a = self._setting(create_new=True, article="Артикул", name="Название",
                                         stock="Остаток", supplier_price="Цена")
        self.warehouse_b = self._setting(create_new=True, article="Артикул", name="Название",
                                         stock="Остаток", supplier_price="Цена")

    def _load(self, setting, *rows):
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": article, "Название": article, "Остаток": stock, "Цена": "10"} for article, stock in rows
        ]))
        return load_setting(setting.pk)

    def _row(self, article):
        return SupplierProduct.objects.get(supplier=self.supplier, article=article)

    def test_two_settings_of_one_supplier_do_not_clear_each_other(self):
        self._load(self.warehouse_a, ("А-1", "1"), ("А-2", "2"))
        self._load(self.warehouse_b, ("Б-1", "5"))
        self._load(self.warehouse_a, ("А-1", "1"), ("А-2", "2"))

        self.assertEqual([self._row(a).stock for a in ("А-1", "А-2", "Б-1")], [1, 2, 5])
        self.assertEqual(self._row("Б-1").supplier_price, Decimal("10"))

    def test_row_vanished_from_its_file_is_cleared_once_and_released(self):
        self._load(self.warehouse_a, ("А-1", "1"), ("П-1", "3"))
        outcome = self._load(self.warehouse_a, ("А-1", "1"))

        self.assertEqual(outcome.stats["missing"], 1)
        moved = self._row("П-1")
        self.assertIsNone(moved.stock)
        self.assertFalse(moved.source_settings.filter(pk=self.warehouse_a.pk).exists())

        # The product moved to the other file: the old setting no longer clears it.
        self._load(self.warehouse_b, ("П-1", "7"))
        outcome = self._load(self.warehouse_a, ("А-1", "1"))
        self.assertEqual(outcome.stats["missing"], 0)
        self.assertEqual(self._row("П-1").stock, 7)

    def test_only_fields_the_setting_maps_are_cleared(self):
        stock_only = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._load(self.warehouse_a, ("А-1", "1"))
        self._create_supplier_file(stock_only, pd.DataFrame([{"Артикул": "А-1", "Название": "А-1", "Остаток": "4"}]))
        load_setting(stock_only.pk)
        self._create_supplier_file(stock_only, pd.DataFrame([{"Артикул": "Х-1", "Название": "Х-1", "Остаток": "1"}]))

        load_setting(stock_only.pk)

        row = self._row("А-1")
        self.assertEqual((row.stock, row.supplier_price), (None, Decimal("10")))

    def test_apply_counts_counts_only_own_rows_as_missing(self):
        from supplier_product_manager.functions import apply_counts
        self._load(self.warehouse_a, ("А-1", "1"))
        self._load(self.warehouse_b, ("Б-1", "5"))

        counts = apply_counts(self.warehouse_a, [{"article": "А-2", "name": "А-2"}])

        self.assertEqual((counts["created"], counts["missing"]), (1, 1))

    def test_deleting_a_setting_clears_rows_only_it_supplied(self):
        self._load(self.warehouse_a, ("А-1", "1"), ("О-1", "2"))
        self._load(self.warehouse_b, ("О-1", "2"))

        self.warehouse_a.delete()

        only_a = self._row("А-1")
        self.assertEqual((only_a.stock, only_a.supplier_price), (None, None))
        shared = self._row("О-1")
        self.assertEqual((shared.stock, shared.supplier_price), (2, Decimal("10")))

    def test_rows_no_setting_supplies_are_handled_by_any_import_of_the_supplier(self):
        vanished = SupplierProduct.objects.create(supplier=self.supplier, article="Н-1", name="Н-1", stock=5)
        kept = SupplierProduct.objects.create(supplier=self.supplier, article="Н-2", name="Н-2", stock=5)

        outcome = self._load(self.warehouse_a, ("Н-2", "6"))

        self.assertEqual(outcome.stats["missing"], 1)
        vanished.refresh_from_db()
        self.assertIsNone(vanished.stock)
        self.assertEqual(list(kept.source_settings.all()), [self.warehouse_a])
        # Claimed by warehouse A now: warehouse B's import leaves it alone.
        self._load(self.warehouse_b, ("Б-1", "1"))
        self.assertEqual(self._row("Н-2").stock, 6)

    def test_deleting_a_setting_without_mapped_fields_changes_nothing(self):
        self._load(self.warehouse_a, ("А-1", "1"))
        self.warehouse_a.links.all().delete()

        self.warehouse_a.delete()

        self.assertEqual(self._row("А-1").stock, 1)


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class ImportRobustnessTests(TestCase):
    """Импорт не идёт дважды, не пишет при разборе и не ломается от правок, сделанных во время него."""

    _base_setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def setUp(self):
        self._base_setUp()
        self.user = get_user_model().objects.create_user(username="robust", password="x")
        self.client.force_login(self.user)
        self.setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self.supplier_file = self._create_supplier_file(
            self.setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар 1", "Остаток": "3"}]),
        )

    def _import(self, **kwargs):
        return process_supplier_file_import(self.setting.pk, self.user.pk, **kwargs)

    def _hold_lock(self):
        key = f"task-lock:supplier_import:setting:{self.setting.pk}"
        cache.add(key, "held", timeout=60)
        self.addCleanup(cache.delete, key)

    # --- one import of a setting at a time ---------------------------------

    def test_second_import_of_a_busy_setting_is_refused(self):
        self._hold_lock()

        result = self._import()

        self.assertEqual(result["status"], "busy")
        self.assertFalse(ImportRun.objects.filter(setting=self.setting).exists())
        self.assertFalse(SupplierProduct.objects.filter(supplier=self.supplier).exists())
        self.assertTrue(PersistentNotification.objects.filter(
            user=self.user, level="warning", message__contains="уже импортируется").exists())
        # A queued file nobody will process is released for the cleanup.
        self.supplier_file.refresh_from_db()
        self.assertEqual(self.supplier_file.status, SupplierFile.STATUS_ERROR)

    def test_refused_import_leaves_the_file_the_running_import_reads(self):
        ImportRun.objects.create(setting=self.setting, supplier=self.supplier,
                                 supplier_file=self.supplier_file, status=ImportRun.STATUS_RUNNING)
        SupplierFile.objects.filter(pk=self.supplier_file.pk).update(status=SupplierFile.STATUS_RUNNING)
        self._hold_lock()

        self._import()

        self.supplier_file.refresh_from_db()
        self.assertEqual(self.supplier_file.status, SupplierFile.STATUS_RUNNING)

    def test_confirmed_import_that_finds_the_setting_busy_waits_for_confirmation_again(self):
        run = ImportRun.objects.create(
            setting=self.setting, supplier=self.supplier, supplier_file=self.supplier_file,
            status=ImportRun.STATUS_RUNNING, confirmed_by=self.user, confirmed_at=timezone.now(),
        )
        self._hold_lock()

        self._import(confirmed_run_id=run.pk)

        run.refresh_from_db()
        self.assertEqual((run.status, run.confirmed_by_id, run.confirmed_at),
                         (ImportRun.STATUS_NEEDS_CONFIRMATION, None, None))
        # Applying dismissed the confirmation; waiting again, the run gets it back.
        notification = PersistentNotification.objects.get(user=self.user)
        self.assertEqual((notification.kind, notification.ref, notification.link_text),
                         ("confirmation", f"import_run:{run.pk}", "Проверить"))
        self.assertIn("уже импортируется", notification.message)

    def test_lock_is_released_after_a_failed_import(self):
        with mock.patch("supplier_product_manager.tasks.load_setting", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._import()

        self.assertEqual(self._import()["status"], "ok")

    # --- changes made while an import runs ---------------------------------

    def test_file_deleted_during_the_import_does_not_lose_the_result(self):
        real_load = load_setting

        def load_then_delete_file(*args, **kwargs):
            outcome = real_load(*args, **kwargs)
            SupplierFile.objects.filter(pk=self.supplier_file.pk).delete()
            return outcome

        with mock.patch("supplier_product_manager.tasks.load_setting", side_effect=load_then_delete_file):
            result = self._import()

        self.assertEqual(result["status"], "ok")
        run = ImportRun.objects.get(setting=self.setting)
        self.assertEqual((run.status, run.supplier_file_id, run.covered), (ImportRun.STATUS_APPLIED, None, 1))
        self.assertTrue(PersistentNotification.objects.filter(user=self.user, level="success").exists())

    def test_import_keeps_supplier_edits_made_while_it_ran(self):
        from supplier_product_manager import functions
        real_counts = functions.apply_counts

        def counts_while_a_manager_edits(setting, payload):
            setting.supplier  # the import now holds the supplier as it was
            Supplier.objects.filter(pk=self.supplier.pk).update(price_priority=1, name="Переименован")
            return real_counts(setting, payload)

        with mock.patch("supplier_product_manager.functions.apply_counts", side_effect=counts_while_a_manager_edits):
            load_setting(self.setting.pk)

        self.supplier.refresh_from_db()
        self.assertEqual((self.supplier.price_priority, self.supplier.name), (1, "Переименован"))
        self.assertIsNotNone(self.supplier.stock_updated_at)
        self.assertIsNone(self.supplier.price_updated_at)  # the setting maps no price

    # --- parsing is read-only ----------------------------------------------

    def test_parsing_does_not_write(self):
        SupplierProduct.objects.create(supplier=self.supplier, article="Т-1", name="Товар\t1")

        get_sps_result(self.setting, recache=True)

        self.assertEqual(
            list(SupplierProduct.objects.filter(supplier=self.supplier).values_list("name", flat=True)),
            ["Товар\t1"],
        )

    # --- views -------------------------------------------------------------

    def test_import_starts_only_on_post(self):
        url = reverse("setting-upload", kwargs={"pk": self.setting.pk, "state": 1})

        with mock.patch("supplier_product_manager.views.process_supplier_file_import") as task:
            self.assertEqual(self.client.get(url).status_code, 405)
            task.delay.assert_not_called()
            self.client.post(url)

        task.delay.assert_called_once_with(self.setting.pk, self.user.pk)

    def test_upload_keeps_older_files_for_the_cleanup(self):
        running = self.supplier_file
        SupplierFile.objects.filter(pk=running.pk).update(status=SupplierFile.STATUS_RUNNING)
        pending = SupplierFile.objects.create(
            setting=self.setting, status=SupplierFile.STATUS_NEEDS_CONFIRMATION,
            file=SimpleUploadedFile("pending.xlsx", b"x"),
        )
        excel = BytesIO()
        pd.DataFrame([{"Артикул": "А-1", "Название": "Товар 1", "Остаток": "4"}]).to_excel(excel, index=False)

        self.client.post(reverse("supplier-upload", kwargs={"pk": self.supplier.pk}),
                         {"file": SimpleUploadedFile("new.xlsx", excel.getvalue()), "setting": self.setting.pk})

        statuses = dict(self.setting.supplierfiles.values_list("pk", "status"))
        self.assertEqual(len(statuses), 3)
        self.assertEqual(statuses[running.pk], SupplierFile.STATUS_RUNNING)
        self.assertEqual(statuses[pending.pk], SupplierFile.STATUS_ERROR)

        cleanup_supplier_files_task()

        # The running file stays until its import ends; the pending one goes.
        self.assertEqual(set(self.setting.supplierfiles.values_list("pk", flat=True)),
                         {running.pk, max(statuses)})


@override_settings(SUPPLIER_IMPORT_GUARD_RATIO=0.7, SUPPLIER_IMPORT_GUARD_WINDOW=5,
                   SUPPLIER_IMPORT_GUARD_MIN_HISTORY=3,
                   SUPPLIER_IMPORT_GUARD_MISSING_LINKED_SHARE=0.05,
                   SUPPLIER_IMPORT_GUARD_MISSING_LINKED_MIN=10)
class MissingLinkedGuardTests(TestCase):
    """Импорт, который обнулит заметную долю привязанных к ГП строк, ждёт подтверждения.

    Покрытие этого не видит: поставщик, переименовавший товары, даёт столько же
    строк, а привязанные к каталогу уходят в «нет в файле»."""

    setUp = ImportGuardTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting
    _history = ImportGuardTests._history
    _file = ImportGuardTests._file
    _import = ImportGuardTests._import

    def _linked_rows(self, count, prefix="Л"):
        """Строки настройки, привязанные к ГП, как после её прошлого импорта."""
        rows = []
        for i in range(count):
            mp = MainProduct.objects.create(supplier=self.supplier, article=f"{prefix}-{i}", name=f"{prefix} {i}")
            row = SupplierProduct.objects.create(supplier=self.supplier, article=f"{prefix}-{i}", name=f"{prefix} {i}",
                                                 stock=5, supplier_price=Decimal("10"), main_product=mp)
            row.source_settings.add(self.setting)
            rows.append(row)
        return rows

    def _verdict(self, missing_linked, linked_own, setting=None):
        from supplier_product_manager import guard
        setting = setting or self.setting
        for _ in range(3):
            ImportRun.objects.create(setting=setting, supplier=self.supplier, status=ImportRun.STATUS_APPLIED,
                                     covered_price=1, covered_stock=1)
        return guard.evaluate(setting, {
            "covered_price": 1, "covered_stock": 1,
            "missing_linked": missing_linked, "linked_own": linked_own,
        })

    def test_threshold_is_a_share_of_linked_rows_but_at_least_min(self):
        self.assertTrue(self._verdict(9, 100).ok)
        self.assertFalse(self._verdict(10, 100).ok)
        self.assertTrue(self._verdict(99, 2000).ok)
        self.assertEqual(self._verdict(100, 2000).reasons,
                         [{"kind": "missing_linked", "value": 100, "linked": 2000}])

    def test_setting_that_clears_nothing_is_not_held(self):
        setting = self._setting(article="Артикул", name="Название", description="Описание")

        self.assertTrue(self._verdict(500, 500, setting=setting).ok)

    def test_renamed_price_list_waits_despite_normal_coverage(self):
        linked = self._linked_rows(12)
        self._history((12, 12), (12, 12), (12, 12))
        # The same twelve products under new names: coverage as usual.
        self._file([("10", "5")] * 12)

        result = self._import()

        self.assertEqual(result["status"], "needs_confirmation")
        run = ImportRun.objects.get(pk=result["run_id"])
        self.assertEqual(run.guard_reasons, [{"kind": "missing_linked", "value": 12, "linked": 12}])
        self.assertEqual((run.missing, run.missing_linked), (13, 12))
        self.assertEqual(run.reason_lines(), [
            "Нет в файле 12 строк, привязанных к ГП, из 12: у товаров каталога обнулятся остаток и цены",
        ])
        linked[0].refresh_from_db()
        self.assertEqual((linked[0].stock, linked[0].supplier_price), (5, Decimal("10")))

    def test_applied_import_records_cleared_linked_rows(self):
        self._linked_rows(2)
        self._history((2, 2), (2, 2), (2, 2))
        self._file([("10", "1"), ("20", "2")])

        result = self._import()

        self.assertEqual(result["status"], "ok")
        self.assertIn("нет в файле 3 (привязаны к ГП 2)", result["message"])
        run = ImportRun.objects.get(setting=self.setting, status=ImportRun.STATUS_APPLIED, user=self.user)
        self.assertEqual((run.missing, run.missing_linked), (3, 2))


class PriceChangesTests(TestCase):
    """Изменения цен существующих строк считаются и записываются, импорт не задерживают."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def test_changes_are_counted_per_price_field(self):
        from supplier_product_manager.functions import price_changes
        setting = self._setting(article="Артикул", name="Название", supplier_price="Цена", rrp="РРЦ")
        for article, price, rrp in (("А-1", "100", "150"), ("А-2", "50", None), ("А-3", "10", "20")):
            SupplierProduct.objects.create(supplier=self.supplier, article=article, name=article,
                                           supplier_price=Decimal(price), rrp=rrp and Decimal(rrp))

        changes = price_changes(setting, [
            {"article": "А-1", "name": "А-1", "supplier_price": 100.0, "rrp": 150.0},
            {"article": "А-2", "name": "А-2", "supplier_price": 200.0, "rrp": 70.0},  # x4; no old rrp
            {"article": "А-3", "name": "А-3", "supplier_price": 11.0, "rrp": None},
            {"article": "НОВЫЙ", "name": "НОВЫЙ", "supplier_price": 5.0, "rrp": 5.0},
        ])

        self.assertEqual(changes, {
            "supplier_price": {"compared": 3, "changed": 2, "jumps": 1, "median_ratio": 1.1},
            "rrp": {"compared": 1, "changed": 0, "jumps": 0, "median_ratio": 1.0},
        })

    @override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
    def test_jumps_are_recorded_and_shown_but_do_not_hold_the_import(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", supplier_price="Цена")
        SupplierProduct.objects.create(supplier=self.supplier, article="А-1", name="Товар", supplier_price=Decimal("10"))
        self._create_supplier_file(setting, pd.DataFrame([{"Артикул": "А-1", "Название": "Товар", "Цена": "1000"}]))
        user = get_user_model().objects.create_user(username="prices", password="x")

        result = process_supplier_file_import(setting.pk, user.pk)

        self.assertEqual(result["status"], "ok")
        run = ImportRun.objects.get(setting=setting)
        self.assertEqual(run.price_changes,
                         {"supplier_price": {"compared": 1, "changed": 1, "jumps": 1, "median_ratio": 100.0}})
        self.client.force_login(user)
        response = self.client.get(reverse("import-run-confirm", kwargs={"pk": run.pk}))
        self.assertContains(response, "Цена поставщика: больше чем в 2 раза")


class WhitespaceMatchTests(TestCase):
    """Строка файла, которая отличается от товара базы только пробелами, обновляет его, а не создаёт новый.

    Раньше «Товар» и «Товар␠» были разными товарами: импорт создавал новую
    строку, а старую, привязанную к ГП, обнулял как «нет в файле»."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def _row(self, article, name, **fields):
        mp = MainProduct.objects.create(supplier=self.supplier, article=article.strip(), name=name.strip())
        return SupplierProduct.objects.create(supplier=self.supplier, article=article, name=name,
                                              main_product=mp, stock=1, **fields)

    def _load(self, setting, rows):
        self._create_supplier_file(setting, pd.DataFrame(rows))
        return load_setting(setting.pk)

    def _keys(self):
        return sorted(SupplierProduct.objects.filter(supplier=self.supplier).values_list("article", "name", "stock"))

    def test_name_differing_by_whitespace_updates_the_existing_row(self):
        row = self._row("А-1", "Товар ")
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")

        outcome = self._load(setting, [{"Артикул": "А-1", "Название": "Товар", "Остаток": "7"}])

        self.assertEqual(self._keys(), [("А-1", "Товар", 7)])
        renamed = SupplierProduct.objects.get(supplier=self.supplier)
        self.assertEqual((renamed.pk, renamed.main_product_id), (row.pk, row.main_product_id))
        self.assertEqual({k: outcome.stats[k] for k in ("renamed", "created", "updated", "missing")},
                         {"renamed": 1, "created": 0, "updated": 1, "missing": 0})

    def test_whitespace_match_works_without_adding_new_products(self):
        self._row("А-1", "Товар  1")
        setting = self._setting(article="Артикул", name="Название", stock="Остаток")

        self._load(setting, [{"Артикул": "А-1", "Название": "Товар 1", "Остаток": "7"}])

        self.assertEqual(self._keys(), [("А-1", "Товар 1", 7)])

    def test_article_differing_by_whitespace_is_renamed_too(self):
        self._row("А-1 ", "Товар")
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")

        self._load(setting, [{"Артикул": "А-1", "Название": "Товар", "Остаток": "7"}])

        self.assertEqual(self._keys(), [("А-1", "Товар", 7)])

    def test_exact_match_wins_and_its_whitespace_twin_is_not_renamed(self):
        self._row("А-1", "Товар")
        self._row("А-1", "Товар ")
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")

        outcome = self._load(setting, [{"Артикул": "А-1", "Название": "Товар", "Остаток": "7"}])

        self.assertEqual(outcome.stats["renamed"], 0)
        # The twin is simply not in the file: cleared as missing, as before.
        self.assertEqual(self._keys(), [("А-1", "Товар", 7), ("А-1", "Товар ", None)])

    def test_several_whitespace_candidates_load_as_new_with_a_warning(self):
        from supplier_product_manager.functions import duplicate_warning
        self._row("А-1", "Товар ")
        self._row("А-1", " Товар")
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")

        outcome = self._load(setting, [{"Артикул": "А-1", "Название": "Товар", "Остаток": "7"}])

        self.assertEqual((outcome.stats["renamed"], outcome.stats["whitespace_ambiguous"]), (0, 1))
        self.assertIn(("А-1", "Товар", 7), self._keys())
        self.assertIn("отличаются только пробелами сразу от нескольких товаров в базе: 1 (например: А-1)",
                      duplicate_warning(outcome.stats))

    def test_match_by_article_finds_an_article_differing_by_whitespace(self):
        row = self._row("А-1 ", "Товар")
        setting = self._setting(article="Артикул", name="Название", stock="Остаток")
        setting.match_by_article = True
        setting.save()

        self._load(setting, [{"Артикул": "А-1", "Название": "Товар", "Остаток": "7"}])

        self.assertEqual(self._keys(), [("А-1", "Товар", 7)])
        self.assertEqual(SupplierProduct.objects.get(supplier=self.supplier).pk, row.pk)

    def test_file_without_names_finds_an_article_differing_by_whitespace(self):
        self._row("А-1 ", "Товар")
        setting = self._setting(article="Артикул", stock="Остаток")

        self._load(setting, [{"Артикул": "А-1", "Остаток": "7"}])

        self.assertEqual(self._keys(), [("А-1", "Товар", 7)])


class PossibleRenameTests(TestCase):
    """Похожее на переименование не переносится автоматически, а попадает в предупреждение."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def _stats(self, db_rows, file_rows):
        for article, name in db_rows:
            SupplierProduct.objects.create(supplier=self.supplier, article=article, name=name, stock=1)
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame(
            [{"Артикул": article, "Название": name, "Остаток": "1"} for article, name in file_rows]))
        return get_sps_result(setting, recache=True)[1]

    def test_single_row_article_with_a_new_name_is_flagged(self):
        from supplier_product_manager.functions import duplicate_warning
        stats = self._stats([("А-1", "Старое"), ("Б-1", "Другое")], [("А-1", "Новое"), ("Б-1", "Другое")])

        self.assertEqual((stats["possible_renames"], stats["possible_rename_examples"]), (1, ["А-1"]))
        self.assertIn("«Артикул уникален»", duplicate_warning(stats))

    def test_variants_and_new_articles_are_not_flagged(self):
        stats = self._stats(
            [("А-1", "Красный"), ("А-1", "Синий")],
            [("А-1", "Зелёный"), ("НОВЫЙ", "Товар")],
        )

        self.assertEqual(stats["possible_renames"], 0)


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class StripWhitespaceTests(TestCase):
    """Пробелы по краям ячеек не значат ничего: разбор их обрезает, а строки базы с пробелами переименовываются."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def test_cells_are_stripped_and_blank_cells_are_empty(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название",
                                supplier_price="Цена", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "  А-1 ", "Название": "\tТовар  1 ", "Цена": " 10 ", "Остаток": "   "},
            {"Артикул": "А-2", "Название": "Товар 2", "Цена": "20", "Остаток": "3"},
        ]))

        payload, stats = get_sps_result(setting, recache=True)

        self.assertEqual([(r["article"], r["name"], r["supplier_price"], r["stock"]) for r in payload],
                         [("А-1", "Товар 1", 10.0, None), ("А-2", "Товар 2", 20.0, 3.0)])
        self.assertEqual((stats["covered_price"], stats["covered_stock"]), (2, 1))

    def test_rows_stored_with_spaces_are_renamed_in_place_on_the_next_import(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        stored = []
        for i in range(3):
            mp = MainProduct.objects.create(supplier=self.supplier, article=f"А-{i}", name=f"Товар {i}")
            row = SupplierProduct.objects.create(supplier=self.supplier, article=f"А-{i} ", name=f" Товар {i}",
                                                 stock=1, main_product=mp)
            row.source_settings.add(setting)
            stored.append(row)
        self._create_supplier_file(setting, pd.DataFrame(
            [{"Артикул": f"А-{i} ", "Название": f" Товар {i}", "Остаток": "5"} for i in range(3)]))

        user = get_user_model().objects.create_user(username="strip", password="x")
        result = process_supplier_file_import(setting.pk, user.pk)

        self.assertEqual(result["status"], "ok")
        rows = SupplierProduct.objects.filter(supplier=self.supplier).order_by("pk")
        self.assertEqual([(r.pk, r.article, r.name, r.stock, r.main_product_id) for r in rows],
                         [(s.pk, f"А-{i}", f"Товар {i}", 5, s.main_product_id) for i, s in enumerate(stored)])
        run = ImportRun.objects.get(setting=setting)
        self.assertEqual((run.renamed, run.created, run.missing), (3, 0, 0))


class ParseNumberTests(TestCase):
    """Числа, как их пишут поставщики, а не как их хранит Excel."""

    def test_formats_suppliers_use(self):
        from supplier_product_manager.functions import _parse_number
        cases = {
            "1234.5": 1234.5, "1 234,56": 1234.56, "1 234,56": 1234.56, "1.234,56": 1234.56,
            "1,234.56": 1234.56, "1.234.567": 1234567.0, "1'234": 1234.0, "2,5": 2.5, "1e3": 1000.0,
            "0": 0.0, "12 руб.": 12.0, "12руб": 12.0, "$12": 12.0, "12 ₸": 12.0, "12 тг": 12.0,
            ">10": 10.0, ">= 10": 10.0, "10+": 10.0, "более 10": 10.0, "10 шт": 10.0, "10 шт.": 10.0,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_parse_number(text), expected)

    def test_not_a_number_or_not_a_price(self):
        from supplier_product_manager.functions import _parse_number
        for text in (None, float("nan"), "", "-", "—", "-5", "<5", "до 5", "10-20", "по запросу",
                     "есть", "nan", "inf", "5 кг"):
            with self.subTest(text=text):
                self.assertIsNone(_parse_number(text))


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class ParseQualityTests(TestCase):
    """Нераспознанные числа и пропавшие столбцы видны, а не теряются молча."""

    setUp = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def test_unparsed_values_are_counted_with_examples_and_reported(self):
        from supplier_product_manager.functions import duplicate_warning
        setting = self._setting(create_new=True, article="Артикул", name="Название",
                                supplier_price="Цена", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "1 234,50", "Остаток": "есть"},
            {"Артикул": "А-2", "Название": "Товар 2", "Цена": "по запросу", "Остаток": "5"},
            {"Артикул": "А-3", "Название": "Товар 3", "Цена": "-", "Остаток": "есть"},
            {"Артикул": "", "Название": "Итого", "Цена": "сумма", "Остаток": ""},
        ]))

        payload, stats = get_sps_result(setting, recache=True)

        self.assertEqual([(r["article"], r["supplier_price"], r["stock"]) for r in payload],
                         [("А-1", 1234.5, None), ("А-2", None, 5.0)])
        self.assertEqual(stats["unparsed_numbers"], {
            "supplier_price": {"count": 1, "examples": ["по запросу"]},
            "stock": {"count": 2, "examples": ["есть"]},
        })
        self.assertIn("не распознаны как числа: Цена поставщика в валюте поставщика — 1 (например: «по запросу»), "
                      "Остаток — 2 (например: «есть»)", duplicate_warning(stats))

    def test_unparsed_values_are_recorded_on_the_run(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Остаток": "много"},
            {"Артикул": "А-2", "Название": "Товар 2", "Остаток": "3"},
        ]))
        user = get_user_model().objects.create_user(username="parse", password="x")

        result = process_supplier_file_import(setting.pk, user.pk)

        self.assertEqual(result["status"], "ok")
        self.assertIn("не распознаны как числа", result["message"])
        run = ImportRun.objects.get(setting=setting)
        self.assertEqual(run.unparsed_numbers, {"stock": {"count": 1, "examples": ["много"]}})
        self.assertEqual(run.unparsed_lines(), [("Остаток: не число", "1")])

    def test_mapped_column_missing_from_the_file_waits_even_with_history(self):
        setting = self._setting(create_new=True, article="Артикул", name="Название",
                                supplier_price="Цена", stock="Остаток")
        for _ in range(3):
            ImportRun.objects.create(setting=setting, supplier=self.supplier, status=ImportRun.STATUS_APPLIED,
                                     covered_price=1, covered_stock=0)
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "10", "Кол-во": "5"},
        ]))
        user = get_user_model().objects.create_user(username="columns", password="x")

        with self.settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=3):
            result = process_supplier_file_import(setting.pk, user.pk)

        self.assertEqual(result["status"], "needs_confirmation")
        run = ImportRun.objects.get(pk=result["run_id"])
        self.assertEqual(run.missing_columns, [{"key": "stock", "column": "Остаток"}])
        self.assertEqual(run.reason_lines(), [
            "В файле нет столбцов из настройки: «Остаток» (Остаток) — эти поля не обновятся. "
            "Столбцы в файле: «Артикул», «Название», «Цена», «Кол-во»",
        ])

    @override_settings(DEBUG=False)
    def test_header_with_an_empty_column_is_not_missing_even_from_the_cache(self):
        cache.clear()
        self.addCleanup(cache.clear)
        setting = self._setting(create_new=True, article="Артикул", name="Название",
                                supplier_price="Цена", stock="Остаток")
        self._create_supplier_file(setting, pd.DataFrame([
            {"Артикул": "А-1", "Название": "Товар 1", "Цена": "10", "Остаток": None},
        ]))

        for _ in range(2):  # the second parse reads the cached DataFrame
            stats = get_sps_result(setting, recache=True)[1]
            self.assertEqual(stats["missing_columns"], [])


@override_settings(SUPPLIER_IMPORT_GUARD_MIN_HISTORY=0)
class CatalogRefreshTests(TestCase):
    """Применённый импорт сразу ставит пересчёт каталога — один на серию импортов."""

    setUp_base = BasicLoadTests.setUp
    _create_supplier_file = BasicLoadTests._create_supplier_file
    _setting = ImportRefusalReasonTests._setting

    def setUp(self):
        self.setUp_base()
        cache.delete("supplier_import:catalog_refresh_pending")
        self.addCleanup(cache.delete, "supplier_import:catalog_refresh_pending")
        self.user = get_user_model().objects.create_user(username="refresh", password="x")
        self.setting = self._setting(create_new=True, article="Артикул", name="Название", stock="Остаток")

    def _import(self, rows=(("А-1", "3"),)):
        self._create_supplier_file(self.setting, pd.DataFrame(
            [{"Артикул": a, "Название": a, "Остаток": s} for a, s in rows]))
        return process_supplier_file_import(self.setting.pk, self.user.pk)

    def test_applied_imports_share_one_delayed_refresh(self):
        with mock.patch("supplier_product_manager.tasks.refresh_catalog_after_import") as task:
            with self.captureOnCommitCallbacks(execute=True):
                result = self._import()
            with self.captureOnCommitCallbacks(execute=True):
                self._import((("А-2", "1"),))

        task.apply_async.assert_called_once_with(countdown=60)
        self.assertIn("обновятся в течение пары минут", result["message"])

    def test_refused_import_schedules_nothing(self):
        with mock.patch("supplier_product_manager.tasks.refresh_catalog_after_import") as task:
            with self.captureOnCommitCallbacks(execute=True):
                self._import((("", "3"),))

        task.apply_async.assert_not_called()

    def test_refresh_runs_stocks_then_prices_and_frees_the_next_schedule(self):
        from supplier_product_manager.tasks import refresh_catalog_after_import
        cache.add("supplier_import:catalog_refresh_pending", 1)
        calls = []
        with mock.patch("supplier_product_manager.tasks._CATALOG_STEPS", (
            ("test.stocks", 60, lambda: calls.append("stocks")),
            ("test.prices", 60, lambda: calls.append("prices")),
        )):
            result = refresh_catalog_after_import.apply().get()

        self.assertEqual(calls, ["stocks", "prices"])
        self.assertEqual(result, {"test.stocks": "success", "test.prices": "success"})
        self.assertIsNone(cache.get("supplier_import:catalog_refresh_pending"))

    def test_refresh_retries_when_a_scheduled_run_holds_the_lock(self):
        from celery.exceptions import Retry
        from supplier_product_manager.tasks import refresh_catalog_after_import
        cache.add("task-lock:test.prices", "held", timeout=60)
        self.addCleanup(cache.delete, "task-lock:test.prices")
        with mock.patch("supplier_product_manager.tasks._CATALOG_STEPS", (
            ("test.stocks", 60, lambda: 0),
            ("test.prices", 60, lambda: 0),
        )), mock.patch.object(refresh_catalog_after_import, "retry", side_effect=Retry()) as retry:
            with self.assertRaises(Retry):
                refresh_catalog_after_import.run()

        retry.assert_called_once_with(countdown=60)


class SettingFreshnessTests(TestCase):
    """Таблица настроек: когда данные настройки обновлялись и не застыла ли она."""

    setUp = BasicLoadTests.setUp
    _setting = ImportRefusalReasonTests._setting

    def _run(self, setting, status, days_ago):
        run = ImportRun.objects.create(setting=setting, supplier=self.supplier, status=status)
        ImportRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timezone.timedelta(days=days_ago))

    def _html(self):
        user = get_user_model().objects.create_user(username=f"fresh-{ImportRun.objects.count()}", password="x")
        self.client.force_login(user)
        return self.client.get(reverse("settings", kwargs={"pk": self.supplier.pk})).content.decode()

    def test_failed_last_run_shows_when_the_data_last_changed(self):
        setting = self._setting(article="Артикул", stock="Остаток")
        self._run(setting, ImportRun.STATUS_APPLIED, 3)
        self._run(setting, ImportRun.STATUS_REFUSED, 0)

        html = self._html()

        self.assertIn("данные от " + timezone.localtime(timezone.now() - timezone.timedelta(days=3)).strftime("%d.%m"), html)
        self.assertNotIn("давно не обновлялась", html)

    def test_setting_older_than_the_suppliers_interval_is_overdue(self):
        Supplier.objects.filter(pk=self.supplier.pk).update(stock_update_days=2, price_update_days=10)
        frozen = self._setting(article="Артикул", stock="Остаток")
        self._run(frozen, ImportRun.STATUS_APPLIED, 3)
        prices = self._setting(article="Артикул", supplier_price="Цена")
        self._run(prices, ImportRun.STATUS_APPLIED, 3)

        self.assertEqual(self._html().count("давно не обновлялась"), 1)

    def test_no_interval_means_never_overdue(self):
        setting = self._setting(article="Артикул", stock="Остаток")
        self._run(setting, ImportRun.STATUS_APPLIED, 400)

        self.assertNotIn("давно не обновлялась", self._html())
