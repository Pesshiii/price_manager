"""Бренды: синонимы написаний поставщиков, зеркало списка PIM, окно «Бренды».

Первый шаг перехода на «товар = (бренд, артикул)». PIM подменяется на уровне
product.services.brands (fetch_list / upsert_async) — в сеть тесты не ходят.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from main_product_manager.models import MainProduct
from pim_api import ListResult
from product_price_manager.models import PriceManager, PriceManagerBrand
from supplier_manager.models import Supplier
from supplier_product_manager.models import Link, Setting, SupplierProduct

from product.models import Brand, BrandAlias, Product, brand_key
from product.services import brands as service

FETCH = 'product.services.brands.fetch_list'
UPSERT = 'product.services.brands.upsert_async'


def _listing(rows, total=None):
    return ListResult(total=len(rows) if total is None else total, items=rows,
                      truncated=total is not None and total > len(rows))


def ensure_ignored(name='Без бренда'):
    """Синоним «игнорировать», как его засевает миграция product.0020.

    Заводится в тесте, а не берётся из засева: TransactionTestCase (тесты
    миграций) очищает таблицы, и с --keepdb засева в тестовой базе уже нет.
    """
    BrandAlias.objects.get_or_create(name_key=brand_key(name), defaults={'name': name, 'brand': None})


class _BrandFixture(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name='Поставщик')
        self.makita = Brand.objects.create(pim_id='br-makita', name='Makita')
        self.dewalt = Brand.objects.create(pim_id='br-dewalt', name='DeWALT')
        ensure_ignored()

    def _row(self, brand_name, article=None, **fields):
        article = article or f'A-{SupplierProduct.objects.count() + 1}'
        return SupplierProduct.objects.create(
            supplier=self.supplier, article=article, name=f'Товар {article}', brand_name=brand_name, **fields)


class BrandKeyTests(TestCase):
    def test_case_spaces_separators_and_yo_do_not_matter(self):
        self.assertEqual(brand_key('De-Walt'), brand_key('DEWALT'))
        self.assertEqual(brand_key(' de walt '), 'dewalt')
        self.assertEqual(brand_key('Ёлка'), brand_key('елка'))
        self.assertEqual(brand_key('A.B_C'), 'abc')

    def test_scripts_are_not_folded(self):
        """«Зубр» и «Zubr» связывает синоним, а не ключ."""
        self.assertNotEqual(brand_key('Зубр'), brand_key('Zubr'))

    def test_empty(self):
        self.assertEqual(brand_key(None), '')
        self.assertEqual(brand_key(' - . '), '')


class ResolutionTests(_BrandFixture):
    def test_implicit_name_alias_and_unresolved(self):
        BrandAlias.objects.create(name='ДеВолт', brand=self.dewalt)
        rows = [self._row('MAKITA'), self._row('деволт'), self._row('Bosh')]

        stats = service.apply_brand_resolution(SupplierProduct.objects.all())

        for row in rows:
            row.refresh_from_db()
        self.assertEqual([row.brand for row in rows], [self.makita, self.dewalt, None])
        self.assertEqual((stats.unresolved_rows, stats.unresolved_names), (1, ['Bosh']))

    def test_ignored_spelling_resolves_to_no_brand(self):
        """«Без бренда» — синоним без бренда (засевается миграцией product.0020): в очередь не попадает."""
        row = self._row('без  бренда')

        stats = service.apply_brand_resolution(SupplierProduct.objects.all())

        row.refresh_from_db()
        self.assertIsNone(row.brand)
        self.assertEqual(stats.unresolved_rows, 0)
        self.assertEqual(service.unmapped_names(), [])

    def test_a_spelling_that_is_only_separators_is_no_brand(self):
        self._row('-')

        self.assertEqual(service.apply_brand_resolution(SupplierProduct.objects.all()).unresolved_rows, 0)

    def test_duplicate_brand_in_pim_is_not_guessed(self):
        """Два активных бренда с одним ключом (STAYER/Stayer) — выбрать за человека нельзя."""
        Brand.objects.create(pim_id='br-makita-2', name='MAKITA')
        row = self._row('Makita')

        service.apply_brand_resolution(SupplierProduct.objects.all())

        row.refresh_from_db()
        self.assertIsNone(row.brand)
        [item] = service.unmapped_names()
        self.assertTrue(item.ambiguous)

    def test_alias_settles_a_duplicate(self):
        Brand.objects.create(pim_id='br-makita-2', name='MAKITA')
        service.add_alias('makita', self.makita)
        row = self._row('Makita')

        service.apply_brand_resolution(SupplierProduct.objects.all())

        row.refresh_from_db()
        self.assertEqual(row.brand, self.makita)

    def test_inactive_brand_is_not_matched_by_name(self):
        self.makita.is_active = False
        self.makita.save()
        row = self._row('Makita')

        service.apply_brand_resolution(SupplierProduct.objects.all())

        row.refresh_from_db()
        self.assertIsNone(row.brand)

    def test_resolution_does_not_touch_updated_at(self):
        """updated_at — время данных поставщика; сопоставление идёт update(), не save()."""
        row = self._row('Makita')
        past = timezone.now() - timedelta(days=3)
        SupplierProduct.objects.filter(pk=row.pk).update(updated_at=past)

        service.apply_brand_resolution(SupplierProduct.objects.all())

        row.refresh_from_db()
        self.assertEqual((row.brand, row.updated_at), (self.makita, past))

    def test_add_alias_moves_a_spelling_away_from_its_implicit_brand(self):
        row = self._row('Makita')
        service.resolve_all()

        service.add_alias('Makita', self.dewalt)

        row.refresh_from_db()
        self.assertEqual(row.brand, self.dewalt)

    def test_delete_alias_returns_rows_to_the_queue(self):
        alias = service.add_alias('Bosh', self.makita)
        row = self._row('Bosh')
        service.resolve_all()

        service.delete_alias(alias)

        row.refresh_from_db()
        self.assertIsNone(row.brand)
        self.assertEqual([item.name for item in service.unmapped_names()], ['Bosh'])

    def test_queue_groups_by_spelling_and_sorts_by_rows(self):
        other = Supplier.objects.create(name='Другой')
        self._row('Bosh')
        SupplierProduct.objects.create(supplier=other, article='Z', name='Z', brand_name='Bosh')
        self._row('Hitachi')

        items = service.unmapped_names()

        self.assertEqual([(item.name, item.rows, item.suppliers) for item in items],
                         [('Bosh', 2, ['Другой', 'Поставщик']), ('Hitachi', 1, ['Поставщик'])])

    def test_suggestions(self):
        suggestions = service.suggest('Makitta', service.suggestion_keys())

        self.assertEqual(suggestions, [self.makita])


class SyncBrandsTests(_BrandFixture):
    def test_mirrors_the_list_and_deactivates_brands_gone_from_pim(self):
        rows = [
            {'id': 'br-makita', 'name': 'Makita Corp', 'code': 'MKT', 'isActive': True},
            {'id': 'br-new', 'name': 'Hitachi', 'code': None, 'isActive': True},
            {'id': 'br-off', 'name': 'Old', 'code': None, 'isActive': False},
        ]
        with mock.patch(FETCH, return_value=_listing(rows)):
            changed = service.sync_brands_from_pim()

        self.makita.refresh_from_db()
        self.dewalt.refresh_from_db()
        self.assertEqual((self.makita.name, self.makita.code, self.makita.is_active), ('Makita Corp', 'MKT', True))
        self.assertFalse(self.dewalt.is_active)
        self.assertTrue(Brand.objects.get(pim_id='br-new').is_active)
        self.assertFalse(Brand.objects.get(pim_id='br-off').is_active)
        self.assertEqual(changed, 4)

    def test_new_brand_resolves_waiting_rows(self):
        row = self._row('Hitachi')
        rows = [{'id': 'br-makita', 'name': 'Makita'}, {'id': 'br-dewalt', 'name': 'DeWALT'},
                {'id': 'br-new', 'name': 'HITACHI'}]
        with mock.patch(FETCH, return_value=_listing(rows)):
            service.sync_brands_from_pim()

        row.refresh_from_db()
        self.assertEqual(row.brand.pim_id, 'br-new')

    def test_truncated_listing_deactivates_nothing(self):
        with mock.patch(FETCH, return_value=_listing([{'id': 'br-makita', 'name': 'Makita'}], total=2)):
            with self.assertRaises(RuntimeError):
                service.sync_brands_from_pim()

        self.dewalt.refresh_from_db()
        self.assertTrue(self.dewalt.is_active)


class CreatePimBrandTests(_BrandFixture):
    def test_existing_pim_brand_is_mirrored_not_created(self):
        """Бренд могли завести в PIM после синхронизации — второй такой же не создаётся."""
        row = self._row('Hitachi')
        with mock.patch(FETCH, return_value=_listing([{'id': 'br-h', 'name': 'HITACHI'}])), \
                mock.patch(UPSERT) as upsert:
            brand, created = service.create_pim_brand('Hitachi')

        upsert.assert_not_called()
        self.assertFalse(created)
        self.assertEqual(brand.pim_id, 'br-h')
        row.refresh_from_db()
        self.assertEqual(row.brand, brand)

    def test_failed_upsert_that_stored_the_brand_is_found_again(self):
        listings = [_listing([]), _listing([{'id': 'br-h', 'name': 'Hitachi', 'isActive': True}])]
        with mock.patch(FETCH, side_effect=listings), \
                mock.patch(UPSERT, return_value=[{'status': 'Failed', 'message': 'timeout'}]) as upsert:
            brand, created = service.create_pim_brand('  Hitachi ')

        payload = upsert.call_args.args[1][0]
        self.assertEqual(payload, {'entity': 'Brand', 'payload': {'name': 'Hitachi', 'isActive': True}})
        self.assertTrue(created)
        self.assertEqual((brand.pim_id, brand.name), ('br-h', 'Hitachi'))

    def test_not_created_is_an_error_for_the_user(self):
        with mock.patch(FETCH, return_value=_listing([])), \
                mock.patch(UPSERT, return_value=[{'status': 'Failed', 'message': 'Validation failed'}]):
            with self.assertRaisesMessage(service.PimBrandError, 'Validation failed'):
                service.create_pim_brand('Hitachi')
        self.assertFalse(Brand.objects.filter(name='Hitachi').exists())

    def test_unreachable_pim_is_an_error_for_the_user(self):
        """Сетевая ошибка не должна стать 500: HTMX ошибочный ответ не показывает, и кнопка молчала бы."""
        with mock.patch(FETCH, side_effect=ConnectionError('no route')):
            with self.assertRaisesMessage(service.PimBrandError, 'PIM не ответил (ConnectionError)'):
                service.create_pim_brand('Hitachi')

    def test_duplicates_in_pim_are_refused(self):
        rows = [{'id': 'h1', 'name': 'Hitachi'}, {'id': 'h2', 'name': 'HITACHI'}]
        with mock.patch(FETCH, return_value=_listing(rows)), mock.patch(UPSERT) as upsert:
            with self.assertRaisesMessage(service.PimBrandError, 'несколько брендов'):
                service.create_pim_brand('Hitachi')
        upsert.assert_not_called()


class MergeBrandsTests(_BrandFixture):
    def test_moves_everything_and_keeps_one_scope_row_per_rule(self):
        old = Brand.objects.create(pim_id='br-old', name='Makita Old', is_active=False)
        product = Product.objects.create(number='P-1', brand=old)
        row = self._row('Makita Old', brand=old)
        alias = BrandAlias.objects.create(name='MKT', brand=old)
        rule = {'supplier': self.supplier, 'source': 'supplier_price', 'dest': 'basic_price',
                'markup': 0, 'increase': 0}
        both = PriceManager.objects.create(name='Оба', **rule)
        only_old = PriceManager.objects.create(name='Старый', **rule)
        PriceManagerBrand.objects.create(price_manager=both, brand=old)
        PriceManagerBrand.objects.create(price_manager=both, brand=self.makita)
        PriceManagerBrand.objects.create(price_manager=only_old, brand=old)

        service.merge_brands(old, self.makita)

        self.assertFalse(Brand.objects.filter(pk=old.pk).exists())
        for obj in (product, row, alias):
            obj.refresh_from_db()
            self.assertEqual(obj.brand, self.makita)
        self.assertEqual(list(both.brands.all()), [self.makita])
        self.assertEqual(list(only_old.brands.all()), [self.makita])
        self.assertEqual(BrandAlias.objects.get(name_key=brand_key('Makita Old')).brand, self.makita)

    def test_twin_products_stop_the_merge_and_change_nothing(self):
        """(артикул, бренд) — товар: слияние сделало бы два товара одной парой."""
        old = Brand.objects.create(pim_id='br-old', name='Makita Old', is_active=False)
        twin = Product.objects.create(number='p-1', brand=old)
        Product.objects.create(number='P-1', brand=self.makita)

        with self.assertRaisesMessage(service.BrandMergeConflict, '«p-1»'):
            service.merge_brands(old, self.makita)

        twin.refresh_from_db()
        self.assertEqual(twin.brand, old)
        self.assertTrue(Brand.objects.filter(pk=old.pk).exists())


class BrandWindowTests(_BrandFixture):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='brands', password='pw')
        self.client.force_login(self.user)

    def test_page_tabs_render(self):
        self._row('Bosh')
        BrandAlias.objects.create(name='ДеВолт', brand=self.dewalt)
        setting = Setting.objects.create(name='Прайс', supplier=self.supplier, sheet_name='Sheet1')

        unmapped = self.client.get(reverse('brands'))
        brands = self.client.get(reverse('brands'), {'tab': 'brands'})
        aliases = self.client.get(reverse('brands'), {'tab': 'aliases'})

        self.assertContains(unmapped, 'Bosh')
        self.assertContains(unmapped, reverse('setting-update', args=[setting.pk]))
        self.assertContains(brands, 'DeWALT')
        self.assertContains(aliases, 'ДеВолт')

    def test_coverage_counts_supplier_rows_of_the_main_price_list(self):
        mp = MainProduct.objects.create(supplier=self.supplier, article='A-1', name='Дрель')
        self._row('Makita', article='A-1', main_product=mp)
        MainProduct.objects.create(supplier=self.supplier, article='A-2', name='Пила')
        service.resolve_all()
        Link.objects.create(setting=Setting.objects.create(name='С брендом', supplier=self.supplier,
                                                           sheet_name='Sheet1'),
                            key='brand_name', value='Бренд')

        coverage = service.coverage()

        self.assertEqual((coverage.mp_with_brand, coverage.mp_total), (1, 2))
        self.assertEqual(coverage.settings_without_brand, [])

    def test_coverage_counts_an_inherited_brand_as_ignored_not_mapped(self):
        """«Без бренда» на товаре Makita: бренд у строки есть, но не сведённый — от товара."""
        product = Product.objects.create(number='D-1', brand=self.makita)
        mp = MainProduct.objects.create(product=product, supplier=self.supplier, article='A-1', name='Дрель')
        self._row('Без бренда', article='A-1', main_product=mp)
        self._row('DeWALT', article='A-2')
        service.resolve_all()

        coverage = service.coverage()

        self.assertEqual(SupplierProduct.objects.get(article='A-1').brand, self.makita)
        self.assertEqual((coverage.sp_mapped, coverage.sp_ignored), (1, 1))

    def test_map_answers_with_fragments_and_closes_the_modal(self):
        row = self._row('Makitta')

        response = self.client.post(reverse('brand-map'), {'name': 'Makitta', 'action': 'map',
                                                           'brand': self.makita.pk})

        row.refresh_from_db()
        self.assertEqual(row.brand, self.makita)
        self.assertIn('brand-mapped', response.headers['HX-Trigger'])
        self.assertContains(response, 'id="brand-coverage" class="br-coverage" hx-swap-oob="true"')
        self.assertContains(response, 'id="brand-unmapped" hx-swap-oob="true"')
        self.assertEqual(BrandAlias.objects.get(name_key='makitta').created_by, self.user)

    def test_suggestion_button_wins_over_the_list(self):
        row = self._row('Makitta')

        self.client.post(reverse('brand-map'), {'name': 'Makitta', 'action': 'map',
                                                'brand': self.dewalt.pk, 'suggested': self.makita.pk})

        row.refresh_from_db()
        self.assertEqual(row.brand, self.makita)

    def test_map_without_a_brand_rerenders_the_modal(self):
        self._row('Makitta')

        response = self.client.post(reverse('brand-map'), {'name': 'Makitta', 'action': 'map'})

        self.assertContains(response, 'Выберите бренд PIM')
        self.assertNotIn('HX-Trigger', response.headers)

    def test_ignore(self):
        self._row('n/a')

        self.client.post(reverse('brand-map'), {'name': 'n/a', 'action': 'ignore'})

        self.assertIsNone(BrandAlias.objects.get(name_key='n/a').brand)
        self.assertEqual(service.unmapped_names(), [])

    def test_create_in_pim(self):
        row = self._row('Hitachi')
        with mock.patch(FETCH, side_effect=[_listing([]), _listing([{'id': 'br-h', 'name': 'Hitachi'}])]), \
                mock.patch(UPSERT, return_value=[{'status': 'Created', 'id': 'br-h'}]):
            response = self.client.post(reverse('brand-map'), {'name': 'Hitachi', 'action': 'create',
                                                               'new_name': 'Hitachi'})

        self.assertIn('brand-mapped', response.headers['HX-Trigger'])
        row.refresh_from_db()
        self.assertEqual(row.brand.pim_id, 'br-h')

    def test_create_error_is_shown_in_the_modal(self):
        self._row('Hitachi')
        with mock.patch(FETCH, return_value=_listing([])), \
                mock.patch(UPSERT, return_value=[{'status': 'Failed', 'message': 'Validation failed'}]):
            response = self.client.post(reverse('brand-map'), {'name': 'Hitachi', 'action': 'create',
                                                               'new_name': 'Hitachi'})

        self.assertContains(response, 'Validation failed')

    def test_map_modal_shows_suggestions(self):
        self._row('Makitta')

        response = self.client.get(reverse('brand-map'), {'name': 'Makitta'})

        self.assertContains(response, f'name="suggested" value="{self.makita.pk}"')

    def test_alias_update_and_delete(self):
        alias = BrandAlias.objects.create(name='ДеВолт', brand=self.dewalt)
        row = self._row('ДеВолт')
        service.resolve_all()

        self.client.post(reverse('brand-alias-update', args=[alias.pk]), {'brand': self.makita.pk})
        row.refresh_from_db()
        self.assertEqual(row.brand, self.makita)

        self.client.post(reverse('brand-alias-update', args=[alias.pk]), {'delete': 'true'})
        row.refresh_from_db()
        self.assertIsNone(row.brand)
        self.assertFalse(BrandAlias.objects.filter(pk=alias.pk).exists())

    def test_merge_view_only_for_inactive_brands(self):
        old = Brand.objects.create(pim_id='br-old', name='Old', is_active=False)

        self.assertEqual(self.client.get(reverse('brand-merge', args=[self.makita.pk])).status_code, 404)
        response = self.client.post(reverse('brand-merge', args=[old.pk]), {'brand': self.makita.pk})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Brand.objects.filter(pk=old.pk).exists())

    def test_sync_button_queues_the_task(self):
        with mock.patch('product.brand_views.sync_brands_task') as task:
            response = self.client.post(reverse('brands-sync'), {'tab': 'brands'})

        task.delay.assert_called_once_with()
        self.assertRedirects(response, f"{reverse('brands')}?tab=brands", fetch_redirect_response=False)
