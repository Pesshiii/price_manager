from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from supplier_feed.tests.fixtures import make_product, make_supplier


@override_settings(SECURE_SSL_REDIRECT=False)
class ProductSnapshotApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='snap_u', password='p')
        cls.product = make_product()
        cls.supplier = make_supplier()

    def setUp(self):
        self.client.force_login(self.user)

    def _list(self, **params):
        return self.client.get(reverse('transform_api:productsnapshot-list'), params)

    def _detail(self, pk):
        return self.client.get(reverse('transform_api:productsnapshot-detail', args=[pk]))


from transform.models import ProductSnapshot


def make_snapshot(product, supplier, data=None, source_feed=None):
    return ProductSnapshot.objects.create(
        product=product,
        supplier=supplier,
        source_feed=source_feed,
        data=data or {},
    )


# --- Cycle 1: tracer bullet -------------------------------------------------

class ListEndpointTest(ProductSnapshotApiBase):
    def test_list_returns_200_empty(self):
        resp = self._list()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['results'], [])


# --- Cycle 2: list with fixtures --------------------------------------------

class ListWithFixturesTest(ProductSnapshotApiBase):
    def test_list_returns_created_snapshot(self):
        snap = make_snapshot(self.product, self.supplier, data={'price': 99})
        resp = self._list()
        self.assertEqual(resp.status_code, 200)
        results = resp.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], snap.id)
        self.assertEqual(results[0]['product'], self.product.id)
        self.assertEqual(results[0]['supplier'], self.supplier.id)
        self.assertEqual(results[0]['data'], {'price': 99})


# --- Cycle 3: filter by product ---------------------------------------------

class ProductFilterTest(ProductSnapshotApiBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_product = make_product(sku='OTHER-001', name='Other')

    def test_filter_returns_matching_snapshot(self):
        snap = make_snapshot(self.product, self.supplier)
        resp = self._list(product=self.product.id)
        results = resp.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], snap.id)

    def test_filter_excludes_other_product(self):
        other_supplier = make_supplier(name='Other Supplier')
        make_snapshot(self.other_product, other_supplier)
        resp = self._list(product=self.product.id)
        self.assertEqual(resp.json()['results'], [])


# --- Cycle 4: filter by supplier --------------------------------------------

class SupplierFilterTest(ProductSnapshotApiBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_supplier = make_supplier(name='Supplier B')
        cls.other_product = make_product(sku='OTHER-002', name='Other2')

    def test_filter_returns_matching_snapshot(self):
        snap = make_snapshot(self.product, self.supplier)
        resp = self._list(supplier=self.supplier.id)
        results = resp.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], snap.id)

    def test_filter_excludes_other_supplier(self):
        make_snapshot(self.other_product, self.other_supplier)
        resp = self._list(supplier=self.supplier.id)
        self.assertEqual(resp.json()['results'], [])


# --- Cycle 5: combined filter -----------------------------------------------

class CombinedFilterTest(ProductSnapshotApiBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_supplier = make_supplier(name='Supplier C')
        cls.other_product = make_product(sku='OTHER-003', name='Other3')

    def test_combined_filter_returns_intersection(self):
        snap = make_snapshot(self.product, self.supplier)
        make_snapshot(self.other_product, self.other_supplier)
        resp = self._list(product=self.product.id, supplier=self.supplier.id)
        results = resp.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], snap.id)

    def test_combined_filter_no_match(self):
        make_snapshot(self.product, self.supplier)
        resp = self._list(product=self.product.id, supplier=self.other_supplier.id)
        self.assertEqual(resp.json()['results'], [])


# --- Cycle 6: retrieve detail -----------------------------------------------

class RetrieveSnapshotTest(ProductSnapshotApiBase):
    def test_get_detail_returns_snapshot(self):
        snap = make_snapshot(self.product, self.supplier, data={'stock': 5})
        resp = self._detail(snap.id)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['id'], snap.id)
        self.assertEqual(body['data'], {'stock': 5})

    def test_unknown_pk_returns_404(self):
        resp = self._detail(99999)
        self.assertEqual(resp.status_code, 404)


# --- Cycle 7: read-only enforcement -----------------------------------------

class ReadOnlyEnforcementTest(ProductSnapshotApiBase):
    def _post(self, payload):
        return self.client.post(
            reverse('transform_api:productsnapshot-list'),
            payload,
            content_type='application/json',
        )

    def test_post_returns_405(self):
        resp = self._post({'product': self.product.id, 'supplier': self.supplier.id, 'data': {}})
        self.assertEqual(resp.status_code, 405)

    def test_put_returns_405(self):
        snap = make_snapshot(self.product, self.supplier)
        resp = self.client.put(
            reverse('transform_api:productsnapshot-detail', args=[snap.id]),
            {'product': self.product.id, 'supplier': self.supplier.id, 'data': {}},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 405)

    def test_delete_returns_405(self):
        snap = make_snapshot(self.product, self.supplier)
        resp = self.client.delete(reverse('transform_api:productsnapshot-detail', args=[snap.id]))
        self.assertEqual(resp.status_code, 405)
