import csv
import io
import os
import tempfile

from django.core.management import call_command
from django.test import TestCase

from main_product_manager.models import MainProduct
from supplier_manager.models import Manufacturer, Supplier
from supplier_product_manager.models import SupplierProduct

from product.models import Brand, Product
from product.services.manufacturer_export import (
    HEADER,
    STATUS_DISAGREES,
    STATUS_NO_BRAND,
    build_manufacturer_export,
)


class ManufacturerExportTests(TestCase):
    """Фикстуры — на пустой базе, как в CI; снимок прода тут не нужен."""

    @classmethod
    def setUpTestData(cls):
        cls.s1 = Supplier.objects.create(name='Поставщик 1')
        cls.s2 = Supplier.objects.create(name='Поставщик 2')
        cls.maker_a = Manufacturer.objects.create(name='MakerA')
        cls.maker_b = Manufacturer.objects.create(name='MakerB')
        cls.maker_a_upper = Manufacturer.objects.create(name='MAKERA')
        cls.brand_x = Brand.objects.create(pim_id='br-x', name='BrandX')
        cls.brand_a = Brand.objects.create(pim_id='br-a', name='MakerA')
        cls.seq = 0

    def _product(self, number, *, name=None, brand=None):
        return Product.objects.create(pim_id=None, number=number, name=name, brand=brand)

    def _offer(self, product, supplier, manufacturer, *, mp_name='Название поставщика',
               mp_manufacturer=None):
        """Одна строка прайса: SupplierProduct -> MainProduct -> Product."""
        ManufacturerExportTests.seq += 1
        n = ManufacturerExportTests.seq
        mp = MainProduct.objects.create(
            product=product, supplier=supplier, article=f'A{n}', name=mp_name,
            manufacturer=mp_manufacturer,
        )
        return SupplierProduct.objects.create(
            main_product=mp, supplier=supplier, article=f'A{n}', name=mp_name,
            manufacturer=manufacturer,
        )

    def _by_number(self, result):
        rows = {}
        for row in result.rows:
            rows.setdefault(row[0], []).append(row)
        return rows

    def test_product_without_pim_brand_is_exported_with_its_manufacturer(self):
        p = self._product('N-1', name='Товар из PIM')
        self._offer(p, self.s1, self.maker_a)

        rows = self._by_number(build_manufacturer_export())

        self.assertEqual(rows['N-1'], [['N-1', 'Товар из PIM', 'MakerA', '', '', STATUS_NO_BRAND]])

    def test_product_with_a_pim_brand_is_left_out_by_default(self):
        """P2-G4 — это товары БЕЗ бренда в PIM. С брендом выгружать нечего."""
        p = self._product('N-2', brand=self.brand_x)
        self._offer(p, self.s1, self.maker_a)

        result = build_manufacturer_export()

        self.assertNotIn('N-2', self._by_number(result))
        self.assertEqual(result.skipped_with_pim_brand, 1)

    def test_product_with_neither_is_left_out(self):
        """Без производителя выгружать нечего — пустых строк быть не должно."""
        p = self._product('N-3')
        self._offer(p, self.s1, None)

        self.assertNotIn('N-3', self._by_number(build_manufacturer_export()))

    def test_disagreeing_suppliers_give_one_row_each_and_a_flag(self):
        """Спор поставщиков виден, а не разрешён монеткой."""
        p = self._product('N-4')
        self._offer(p, self.s1, self.maker_a)
        self._offer(p, self.s2, self.maker_b)

        result = build_manufacturer_export()
        rows = self._by_number(result)['N-4']

        self.assertEqual([r[2] for r in rows], ['MakerA', 'MakerB'])
        self.assertEqual({r[3] for r in rows}, {'да'})
        self.assertEqual(result.products, 1)
        self.assertEqual(result.products_with_conflict, 1)

    def test_case_variants_are_not_a_disagreement(self):
        p = self._product('N-5')
        self._offer(p, self.s1, self.maker_a)
        self._offer(p, self.s2, self.maker_a_upper)

        rows = self._by_number(build_manufacturer_export())['N-5']

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], '')

    def test_source_is_the_raw_supplier_column_not_main_product(self):
        """sync_pim_relations перезаписывает MainProduct.manufacturer брендом PIM.

        Выгружать его обратно в PIM бессмысленно — выгружается то, что сказал
        поставщик.
        """
        p = self._product('N-6')
        self._offer(p, self.s1, self.maker_a, mp_manufacturer=self.maker_b)

        rows = self._by_number(build_manufacturer_export())['N-6']

        self.assertEqual([r[2] for r in rows], ['MakerA'])

    def test_name_falls_back_to_the_supplier_name_when_pim_has_none(self):
        """У товаров без бренда в PIM чаще всего нет и имени из PIM."""
        p = self._product('N-7', name=None)
        self._offer(p, self.s1, self.maker_a, mp_name='Имя из прайса')

        rows = self._by_number(build_manufacturer_export())['N-7']

        self.assertEqual(rows[0][1], 'Имя из прайса')

    def test_supplier_rows_outside_the_catalog_are_counted_not_dropped_silently(self):
        SupplierProduct.objects.create(
            main_product=None, supplier=self.s1, article='LOOSE', name='Не в каталоге',
            manufacturer=self.maker_a,
        )

        result = build_manufacturer_export()

        self.assertEqual(result.unlinked_supplier_rows, 1)
        self.assertEqual(result.rows, [])

    def test_with_disagreements_adds_pim_brands_no_supplier_confirms(self):
        confirmed = self._product('N-8', brand=self.brand_a)
        self._offer(confirmed, self.s1, self.maker_a)
        disputed = self._product('N-9', brand=self.brand_x)
        self._offer(disputed, self.s1, self.maker_a)

        rows = self._by_number(build_manufacturer_export(include_disagreements=True))

        self.assertNotIn('N-8', rows)
        self.assertEqual(
            rows['N-9'],
            [['N-9', 'Название поставщика', 'MakerA', '', 'BrandX', STATUS_DISAGREES]],
        )


class ExportCommandTests(TestCase):
    def setUp(self):
        supplier = Supplier.objects.create(name='Поставщик')
        product = Product.objects.create(pim_id=None, number='N-1', name='Товар')
        mp = MainProduct.objects.create(product=product, supplier=supplier, article='A', name='x')
        SupplierProduct.objects.create(
            main_product=mp, supplier=supplier, article='A', name='x',
            manufacturer=Manufacturer.objects.create(name='Производитель'),
        )

    def test_stdout_carries_only_the_csv(self):
        """Счётчики идут в stderr — иначе перенаправление в файл их туда и запишет."""
        out, err = io.StringIO(), io.StringIO()

        call_command('export_manufacturers_for_pim', stdout=out, stderr=err)

        rows = list(csv.reader(io.StringIO(out.getvalue())))
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(rows[1][:3], ['N-1', 'Товар', 'Производитель'])
        self.assertEqual(len(rows), 2)
        self.assertIn('Товаров: 1', err.getvalue())

    def test_output_file_has_a_bom_so_excel_reads_cyrillic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.csv')
            call_command('export_manufacturers_for_pim', output=path, stderr=io.StringIO())

            with open(path, 'rb') as fh:
                raw = fh.read()

        self.assertTrue(raw.startswith('﻿'.encode('utf-8')))
        text = raw.decode('utf-8-sig')
        self.assertIn('Производитель', text)
