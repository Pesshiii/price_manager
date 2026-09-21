"""MainProductFilter — выбор строк поставщиков для корзины и «Привязать из ГП».

Главное, что здесь проверяется: фильтр НЕ опирается на search_vector,
categories и manufacturer самого MainProduct — Phase 2 их удаляет. Поиск и
контентные фасеты идут через MainProduct.product.
"""
from django.http import QueryDict
from django.test import TestCase

from core.utils import find_main_products
from product.models import Brand, Category, Product
from supplier_manager.models import Supplier

from .filters import MainProductFilter
from .models import MainProduct


def make_product(number, raw_data=None, **kwargs):
    product = Product.objects.create(pim_id=f'pmp-{number}', number=number,
                                     raw_data=raw_data or {}, **kwargs)
    product.rebuild_search_vector()
    return product


def query(**params):
    data = QueryDict(mutable=True)
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            data.setlist(key, [str(v) for v in value])
        else:
            data[key] = str(value)
    return data


class MainProductFilterTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name='Поставщик')
        self.brand = Brand.objects.create(pim_id='br-1', name='Grohe')
        self.other_brand = Brand.objects.create(pim_id='br-2', name='Philips')

        self.root = Category.objects.create(name='Сантехника')
        self.child = Category.objects.create(parent=self.root, name='Смесители')
        self.electric = Category.objects.create(name='Электрика')

        self.mixer = make_product('SKU-MIX', {'name': 'Смеситель для кухни'}, brand=self.brand)
        self.mixer.categories.add(self.child)
        self.lamp = make_product('SKU-LAMP', {'name': 'Лампа настольная'}, brand=self.other_brand)
        self.lamp.categories.add(self.electric)

        # Название у поставщика нарочно не совпадает с PIM: находиться строка
        # должна по данным товара, а не по своим.
        self.mixer_offer = self._offer('A-100', 'Mixer K1', product=self.mixer)
        self.lamp_offer = self._offer('A-200', 'Lamp L2', product=self.lamp)
        self.unlinked = self._offer('RAW-777', 'Кран шаровой', product=None)

    def _offer(self, article, name, product):
        return MainProduct.objects.create(
            supplier=self.supplier, article=article, name=name, product=product,
            sku=product.number if product else None,
        )

    def _pks(self, **params):
        return list(MainProductFilter(data=query(**params), queryset=MainProduct.objects.all())
                    .qs.values_list('pk', flat=True))

    def test_search_finds_the_row_through_its_products_pim_name(self):
        self.assertEqual(self._pks(search='смеситель'), [self.mixer_offer.pk])

    def test_row_without_a_product_is_still_found_by_its_own_fields(self):
        """В корзине невидимость строки значила бы «нельзя купить»."""
        self.assertEqual(self._pks(search='RAW-777'), [self.unlinked.pk])
        self.assertEqual(self._pks(search='шаровой'), [self.unlinked.pk])

    def test_supplier_article_is_searchable(self):
        """Артикул поставщика важен именно при покупке — на товарной странице
        его нет, здесь он остаётся."""
        self.assertEqual(self._pks(search='A-200'), [self.lamp_offer.pk])

    def test_full_text_match_ranks_above_a_rankless_own_field_match(self):
        """rank у строки без товара — NULL, и при DESC он встал бы ПЕРВЫМ без
        nulls_last."""
        weak = self._offer('SMESITEL-1', 'смеситель без товара', product=None)

        self.assertEqual(self._pks(search='смеситель'), [self.mixer_offer.pk, weak.pk])

    def test_brand_filters_through_the_product(self):
        self.assertEqual(self._pks(brand=[self.brand.pk]), [self.mixer_offer.pk])

    def test_parent_category_finds_rows_of_products_in_its_children(self):
        self.assertEqual(self._pks(categories=[self.root.pk]), [self.mixer_offer.pk])

    def test_product_in_two_selected_categories_gives_the_row_once(self):
        self.mixer.categories.add(self.root)

        self.assertEqual(
            self._pks(categories=[self.root.pk, self.child.pk]), [self.mixer_offer.pk],
        )

    def test_facets_narrow_to_the_search(self):
        """Ищут «лампа» — в фасетах бренд и категории ламп, а не весь справочник."""
        filterset = MainProductFilter(data=query(search='лампа'), queryset=MainProduct.objects.all())

        self.assertEqual(list(filterset.filters['brand'].field.queryset), [self.other_brand])
        self.assertEqual(list(filterset.filters['categories'].field.queryset), [self.electric])

    def test_category_facet_keeps_the_ancestors_of_what_it_shows(self):
        """Дерево рисуется {% recursetree %} — без предков узел повис бы в воздухе."""
        filterset = MainProductFilter(data=query(search='смеситель'),
                                      queryset=MainProduct.objects.all())

        self.assertEqual(
            set(filterset.filters['categories'].field.queryset), {self.root, self.child},
        )

    def test_selected_brand_stays_in_the_facet_when_the_search_excludes_it(self):
        """Иначе галочку, сузившую выдачу до нуля, нечем было бы снять."""
        filterset = MainProductFilter(data=query(search='лампа', brand=[self.brand.pk]),
                                      queryset=MainProduct.objects.all())

        brands = list(filterset.filters['brand'].field.queryset)
        self.assertEqual(brands[0], self.brand)
        self.assertIn(self.other_brand, brands)

    def test_a_plain_dict_does_not_break_the_filter(self):
        filterset = MainProductFilter(data={'search': 'лампа', 'brand': str(self.other_brand.pk)},
                                      queryset=MainProduct.objects.all())

        self.assertEqual(list(filterset.qs), [self.lamp_offer])

    def test_find_main_products_uses_the_same_search(self):
        """Автоподбор при импорте заявки — тот же поиск, что и в модалке."""
        self.assertEqual(find_main_products('смеситель'), [self.mixer_offer])
        self.assertEqual(find_main_products('   '), [])
