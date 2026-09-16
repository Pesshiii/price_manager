from decimal import Decimal

from django.test import TestCase

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier

from product.filters import ProductFilter
from product.models import Brand, Category, Product


def make_product(pim_id, number, raw_data=None, **kwargs):
    product = Product.objects.create(
        pim_id=pim_id, number=number, raw_data=raw_data or {}, **kwargs
    )
    product.rebuild_search_vector()
    return product


class ProductSearchFilterTests(TestCase):
    def setUp(self):
        self.mixer = make_product(
            'pmp-1', 'SKU-MIX',
            raw_data={'name': 'Смеситель для кухни', 'categoriesNames': {'c': 'Сантехника'}},
        )
        self.lamp = make_product('pmp-2', 'SKU-LAMP', raw_data={'name': 'Лампа настольная'})

    def _filter(self, **params):
        return ProductFilter(params, queryset=Product.objects.all()).qs

    def test_finds_by_word_from_the_search_vector(self):
        self.assertEqual(list(self._filter(search='смеситель')), [self.mixer])

    def test_finds_by_category_name_from_the_vector(self):
        self.assertEqual(list(self._filter(search='сантехника')), [self.mixer])

    def test_finds_by_number(self):
        self.assertEqual(list(self._filter(search='SKU-LAMP')), [self.lamp])

    def test_finds_unsynced_product_by_its_main_product_name(self):
        """Заготовка без данных PIM всё равно должна находиться.

        У неё вектор состоит из одного number, и без этого условия найти такой
        товар нельзя вообще ничем, пока бэкфилл до него не дошёл.
        """
        blank = make_product('pmp-3', 'SKU-BLANK')
        MainProduct.objects.create(product=blank, article='A1', name='Уникальное Имя Поставщика')

        self.assertEqual(list(self._filter(search='Уникальное')), [blank])

    def test_empty_search_returns_everything(self):
        self.assertEqual(self._filter(search='').count(), 2)

    def test_search_does_not_duplicate_rows(self):
        """Условие по main_products — Exists, а не join.

        Join размножил бы товар по числу поставщиков.
        """
        product = make_product('pmp-4', 'SKU-DUP', raw_data={'name': 'Дубликат'})
        for i in range(3):
            supplier = Supplier.objects.create(name=f'Поставщик {i}')
            MainProduct.objects.create(
                product=product, supplier=supplier, article=f'A{i}', name='Дубликат',
            )

        self.assertEqual(self._filter(search='Дубликат').count(), 1)


class ProductCategoryFilterTests(TestCase):
    def setUp(self):
        self.root = Category.objects.create(name='Сантехника')
        self.child = Category.objects.create(parent=self.root, name='Смесители')
        self.grandchild = Category.objects.create(parent=self.child, name='Кухонные')
        self.other = Category.objects.create(name='Электрика')

        self.deep = make_product('pmp-1', 'SKU-DEEP')
        self.deep.categories.add(self.grandchild)
        self.unrelated = make_product('pmp-2', 'SKU-OTHER')
        self.unrelated.categories.add(self.other)

    def _filter(self, category):
        return ProductFilter(
            {'categories': [str(category.pk)]}, queryset=Product.objects.all()
        ).qs

    def test_selecting_a_parent_finds_products_in_its_descendants(self):
        """Выбор родителя должен находить всё, что под ним.

        Разворот по дереву делается локально через MPTT. Без него выбор
        «Сантехника» вернул бы пусто — товар висит на внуке, — и вернул бы
        молча, без ошибки.
        """
        self.assertEqual(list(self._filter(self.root)), [self.deep])

    def test_selecting_an_intermediate_node_also_works(self):
        self.assertEqual(list(self._filter(self.child)), [self.deep])

    def test_unrelated_branch_is_not_matched(self):
        self.assertEqual(list(self._filter(self.other)), [self.unrelated])

    def test_category_filter_does_not_duplicate_rows(self):
        """Товар в нескольких категориях одной ветки — всё равно одна строка."""
        self.deep.categories.add(self.root, self.child)

        self.assertEqual(self._filter(self.root).count(), 1)


class ProductBrandFilterTests(TestCase):
    def setUp(self):
        self.grohe = Brand.objects.create(pim_id='br-1', name='Grohe')
        self.bosch = Brand.objects.create(pim_id='br-2', name='Bosch')
        self.a = make_product('pmp-1', 'SKU-A', brand=self.grohe)
        self.b = make_product('pmp-2', 'SKU-B', brand=self.bosch)

    def test_filters_by_brand(self):
        qs = ProductFilter({'brand': [str(self.grohe.pk)]}, queryset=Product.objects.all()).qs
        self.assertEqual(list(qs), [self.a])

    def test_facet_lists_only_brands_that_are_used(self):
        Brand.objects.create(pim_id='br-3', name='Неиспользуемый')
        filterset = ProductFilter({}, queryset=Product.objects.all())

        names = list(filterset.filters['brand'].field.queryset.values_list('name', flat=True))
        self.assertEqual(names, ['Bosch', 'Grohe'])


class ProductStockAndPriceFilterTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name='Поставщик')
        self.other_supplier = Supplier.objects.create(name='Другой')

        self.in_stock = make_product('pmp-1', 'SKU-IN')
        MainProduct.objects.create(
            product=self.in_stock, supplier=self.supplier, article='A1', name='Есть',
            stock=5, prime_cost=Decimal('100.00'),
        )
        self.out_of_stock = make_product('pmp-2', 'SKU-OUT')
        MainProduct.objects.create(
            product=self.out_of_stock, supplier=self.other_supplier, article='A2', name='Нет',
            stock=0, prime_cost=Decimal('900.00'),
        )

    def _filter(self, **params):
        return ProductFilter(params, queryset=Product.objects.all()).qs

    def test_available_keeps_only_products_with_stock(self):
        self.assertEqual(list(self._filter(available='true')), [self.in_stock])

    def test_supplier_filter(self):
        self.assertEqual(
            list(self._filter(supplier=[str(self.supplier.pk)])), [self.in_stock]
        )

    def test_price_range(self):
        self.assertEqual(list(self._filter(price_from='500')), [self.out_of_stock])
        self.assertEqual(list(self._filter(price_to='500')), [self.in_stock])

    def test_never_returns_a_product_twice_when_several_suppliers_match(self):
        """Два поставщика в наличии — товар всё равно одна строка."""
        third = Supplier.objects.create(name='Третий')
        MainProduct.objects.create(
            product=self.in_stock, supplier=third, article='A3', name='Есть',
            stock=7, prime_cost=Decimal('110.00'),
        )

        self.assertEqual(self._filter(available='true').count(), 1)
