from decimal import Decimal

from django.http import QueryDict
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

    def test_full_text_match_ranks_above_a_supplier_name_only_match(self):
        """Настоящее полнотекстовое совпадение обязано идти выше слабого.

        Регрессия, найденная на снимке прода: '-rank' компилируется в ORDER BY
        rank DESC, а Postgres при DESC ставит NULL первыми. У товара без данных
        PIM нет вектора, его rank — NULL, и на «молоток» ВСЯ первая страница
        (25 из 25) состояла из совпадений только по названию у поставщика, а
        463 настоящих полнотекстовых на неё не попадали. Весь набор тестов при
        этом был зелёным: ни один не проверял порядок, только состав.
        """
        weak = Product.objects.create(pim_id='pmp-weak', number='SKU-WEAK', raw_data={})
        # Вектор намеренно не собираем — так выглядит товар без данных PIM.
        MainProduct.objects.create(product=weak, article='W1', name='Кувалда поставщика')

        strong = make_product('pmp-strong', 'SKU-STRONG',
                              raw_data={'name': 'Кувалда стальная'})

        results = list(self._filter(search='кувалда'))

        self.assertEqual(set(results), {weak, strong})
        self.assertEqual(results[0], strong)

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
        filterset.narrow_facets()

        names = list(filterset.form.fields['brand'].queryset.values_list('name', flat=True))
        self.assertEqual(names, ['Bosch', 'Grohe'])

    def test_any_existing_brand_validates_without_narrowing(self):
        """Бренд без товаров в адресе — не ошибка формы, а пустая выдача.

        Проверка значений идёт по всему справочнику: сужает только
        narrow_facets(), которого .qs не вызывает.
        """
        unused = Brand.objects.create(pim_id='br-3', name='Неиспользуемый')
        filterset = ProductFilter({'brand': [str(unused.pk)]}, queryset=Product.objects.all())

        self.assertTrue(filterset.form.is_valid())
        self.assertEqual(list(filterset.qs), [])


class ProductFacetNarrowingTests(TestCase):
    """Фасеты сужаются под выдачу: «все условия, кроме своего».

    Главный инвариант: число рядом с вариантом равно тому, что покажет выбор
    этого варианта вместе с остальными текущими условиями.
    """

    def setUp(self):
        self.bosch = Brand.objects.create(pim_id='br-1', name='Bosch')
        self.makita = Brand.objects.create(pim_id='br-2', name='Makita')
        self.grohe = Brand.objects.create(pim_id='br-3', name='Grohe')

        self.tools = Category.objects.create(pim_id='c-1', name='Инструмент')
        self.drills = Category.objects.create(pim_id='c-2', name='Дрели', parent=self.tools)
        self.saws = Category.objects.create(pim_id='c-3', name='Пилы', parent=self.tools)
        self.plumbing = Category.objects.create(pim_id='c-4', name='Сантехника')

        self.alpha = Supplier.objects.create(name='Альфа')
        self.beta = Supplier.objects.create(name='Бета')

        self.drill = make_product('p-1', 'D-1', brand=self.bosch,
                                  raw_data={'name': 'Дрель ударная'})
        self.drill.categories.add(self.drills)
        # Один товар в двух подкатегориях одной ветки: у «Инструмента» он
        # обязан считаться один раз.
        self.combo = make_product('p-2', 'C-1', brand=self.makita,
                                  raw_data={'name': 'Набор дрель и пила'})
        self.combo.categories.add(self.drills, self.saws)
        self.mixer = make_product('p-3', 'M-1', brand=self.grohe,
                                  raw_data={'name': 'Смеситель'})
        self.mixer.categories.add(self.plumbing)

        MainProduct.objects.create(product=self.drill, supplier=self.alpha, article='a1',
                                   stock=3)
        MainProduct.objects.create(product=self.combo, supplier=self.alpha, article='a2',
                                   stock=0)
        MainProduct.objects.create(product=self.combo, supplier=self.beta, article='b2',
                                   stock=0)
        MainProduct.objects.create(product=self.mixer, supplier=self.beta, article='b3',
                                   stock=1)

    def _facets(self, data):
        filterset = ProductFilter(QueryDict(data), queryset=Product.objects.all())
        filterset.narrow_facets()
        return filterset

    @staticmethod
    def _visible(filterset, name):
        field = filterset.form.fields[name]
        return {obj.pk: field.facet_counts.get(obj.pk, 0) for obj in field.queryset}

    def test_unfiltered_counts(self):
        facets = self._facets('')

        self.assertEqual(self._visible(facets, 'brand'),
                         {self.bosch.pk: 1, self.makita.pk: 1, self.grohe.pk: 1})
        self.assertEqual(self._visible(facets, 'supplier'),
                         {self.alpha.pk: 2, self.beta.pk: 2})
        self.assertEqual(self._visible(facets, 'categories'), {
            self.tools.pk: 2, self.drills.pk: 2, self.saws.pk: 1, self.plumbing.pk: 1,
        })

    def test_selecting_a_brand_keeps_the_other_brands(self):
        facets = self._facets(f'brand={self.bosch.pk}')

        self.assertEqual(set(self._visible(facets, 'brand')),
                         {self.bosch.pk, self.makita.pk, self.grohe.pk})

    def test_selecting_a_brand_narrows_suppliers_and_categories(self):
        facets = self._facets(f'brand={self.grohe.pk}')

        self.assertEqual(self._visible(facets, 'supplier'), {self.beta.pk: 1})
        self.assertEqual(self._visible(facets, 'categories'), {self.plumbing.pk: 1})

    def test_selecting_a_supplier_narrows_brands(self):
        facets = self._facets(f'supplier={self.alpha.pk}')

        self.assertEqual(self._visible(facets, 'brand'),
                         {self.bosch.pk: 1, self.makita.pk: 1})

    def test_search_and_stock_narrow_the_facets(self):
        facets = self._facets('search=дрель&available=on')

        self.assertEqual(self._visible(facets, 'brand'), {self.bosch.pk: 1})
        self.assertEqual(self._visible(facets, 'supplier'), {self.alpha.pk: 1})
        self.assertEqual(self._visible(facets, 'categories'),
                         {self.tools.pk: 1, self.drills.pk: 1})

    def test_selected_option_with_no_products_stays_with_its_ancestors(self):
        """Иначе снять такую галочку нечем, а дерево без предка — это 500."""
        facets = self._facets(f'brand={self.grohe.pk}&categories={self.saws.pk}')

        self.assertEqual(self._visible(facets, 'categories'), {
            self.plumbing.pk: 1, self.tools.pk: 0, self.saws.pk: 0,
        })
        self.assertIn(self.grohe.pk, self._visible(facets, 'brand'))

    def test_every_count_matches_selecting_that_option(self):
        base = f'available=on&supplier={self.beta.pk}'
        facets = self._facets(base)
        # Ноль у видимого варианта бывает только у выбранного — проверяем все.
        for name in ProductFilter.FACETS:
            for pk, count in self._visible(facets, name).items():
                with self.subTest(facet=name, pk=pk):
                    data = QueryDict(base, mutable=True)
                    data.setlist(name, [str(pk)])
                    actual = ProductFilter(data, queryset=Product.objects.all()).qs.count()
                    self.assertEqual(count, actual)

    def test_junk_in_the_address_does_not_break_narrowing(self):
        facets = self._facets('brand=abc&categories=999999&supplier=')

        self.assertEqual(len(self._visible(facets, 'brand')), 3)


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
