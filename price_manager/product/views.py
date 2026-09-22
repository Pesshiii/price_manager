import logging

from django.db.models import OuterRef, Prefetch, Subquery
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import View
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin

from main_product_manager.models import MainProduct
from main_product_manager.utils import fetch_pim_image
from supplier_product_manager.models import SupplierProduct

from .columns import PRODUCT_COLUMN_GROUPS, load_columns, save_columns
from .filters import CATEGORY_LABEL_DEPTH, ProductFilter, search_terms
from .models import Category, Product
from .tables import (
    ProductTable, SupplierRowTable, annotate_product_rows, best_match_groups_first,
    with_category_headers,
)

logger = logging.getLogger(__name__)


def _base_queryset(by_category=False):
    """Товары для страницы.

    select_related('brand') и prefetch категорий — ячейка названия выводит под
    ним бренд и категории (ProductTable.render_display_name) на каждой строке,
    без этого страница даёт N+1 на обеих связях. Категории предзагружаются
    вместе с предками: из них строится путь в заголовке группы
    (tables.category_path), и без select_related каждый шаг к корню был бы
    запросом.
    """
    categories = Category.objects.select_related(CATEGORY_LABEL_DEPTH)
    return annotate_product_rows(
        Product.objects.select_related('brand')
        .prefetch_related(Prefetch('categories', queryset=categories)),
        by_category=by_category,
    )


def unlinked_main_product_count() -> int:
    """Сколько строк поставщиков не видно на этой странице.

    Товарная страница растёт от Product, поэтому MainProduct без привязки на
    неё не попадает вообще — это принятое решение, а не дефект. Но принятая
    невидимость должна остаться наблюдаемой: без счётчика никто никогда не
    узнает, что часть прайса выпала, и страница будет выглядеть полной.
    """
    return MainProduct.objects.filter(product__isnull=True).count()


class ProductPage(SingleTableMixin, FilterView):
    """Товарная страница: плоский список Product.

    Категорийного сайдбара здесь нет намеренно — категории живут в фильтре
    слева. Это отличие от главной страницы, которая построена вокруг
    постранично выдаваемых таблиц по категориям.

    SingleTableMixin, а не голый FilterView: таблица отрисовывается прямо в
    странице, поэтому `table` должен быть в контексте. Главная устроена иначе —
    там таблицы догружаются отдельными запросами по категориям.
    """

    model = Product
    filterset_class = ProductFilter
    table_class = ProductTable
    template_name = 'product/list.html'
    table_pagination = {'per_page': 25}

    def get_template_names(self):
        """HTMX-запрос получает только таблицу, обычный — страницу целиком.

        И фильтр, и строка поиска бьют hx-get сюда же, в 'products', а не в
        отдельный эндпоинт: так hx-push-url кладёт в адресную строку
        /products/?…, который потом честно открывается и перезагружается. Если
        бы они ходили за фрагментом, в адресной строке оказался бы адрес
        фрагмента.

        Расплата за это — представление обязано отдавать фрагмент само. Без
        этой ветки ответом на hx-get приходит list.html целиком и вставляется
        внутрь #products-table: страница в странице. Главная решает это тем же
        способом.
        """
        if self.request.htmx:
            return ['product/partials/table.html']
        return [self.template_name]

    def get_queryset(self):
        return _base_queryset(by_category=self.groups_by_category())

    def groups_by_category(self):
        """Выдача по категориям — порядок по умолчанию.

        Выключает её только сортировка по колонке: пользователь выбрал свой
        порядок, и заголовки категорий посреди него резали бы выдачу на куски.
        Поиск её не выключает — он лишь переставляет группы по лучшему
        совпадению (get_table_data). Имя параметра сортировки — из Meta
        таблицы: таблицы в момент get_queryset ещё нет.
        """
        sort_field = ProductTable._meta.prefix + ProductTable._meta.order_by_field
        return not self.request.GET.get(sort_field)

    def get_table_data(self):
        """Поиск в выдаче по категориям: группа с лучшим совпадением — первой.

        search_method уже заменил порядок по категориям порядком по
        релевантности (filters.ranked), и заголовки над ним пошли бы почти над
        каждой строкой. Порядок по категориям в дереве, наоборот, увёл бы
        лучшее совпадение на дальнюю страницу. Здесь — середина: группы по
        лучшему совпадению, внутри группы — по релевантности.
        """
        data = super().get_table_data()
        if self.groups_by_category() and search_terms(self.request.GET.get('search')):
            data = best_match_groups_first(data)
        return data

    def selected_columns(self):
        """Выбор колонок: из запроса — сохраняется, иначе — сохранённый ранее.

        Выбор приходит тем же hx-get, что и фильтр, поэтому отвечает на него
        та же таблица, и представлению не нужен отдельный эндпоинт.
        """
        if not hasattr(self, '_selected_columns'):
            if 'columns' in self.request.GET:
                self._selected_columns = save_columns(
                    self.request.user, self.request.GET.getlist('columns'))
            else:
                self._selected_columns = load_columns(self.request.user)
        return self._selected_columns

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        kwargs['request'] = self.request
        kwargs['selected_columns'] = self.selected_columns()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['column_groups'] = PRODUCT_COLUMN_GROUPS
        context['selected_columns'] = self.selected_columns()
        context['unlinked_main_products'] = unlinked_main_product_count()
        context['unsynced_products'] = Product.objects.filter(raw_data={}).count()
        # Номера страниц с многоточиями (1 … 4 5 6 … 6314): в шаблоне вызвать
        # метод с аргументами нельзя, поэтому диапазон считается здесь.
        table = context['table']
        if table.page:
            context['page_range'] = table.paginator.get_elided_page_range(
                table.page.number, on_each_side=1, on_ends=1)
        # Строки страницы парами (заголовок категории или None, строка): шаблон
        # один и тот же для обоих режимов и сам ничего не решает.
        grouped = self.groups_by_category()
        context['group_by_category'] = grouped
        rows = table.paginated_rows
        context['product_rows'] = (with_category_headers(rows) if grouped
                                   else [(None, row) for row in rows])
        return context


class ProductFilterView(View):
    """Отдаёт панель фильтров отдельным запросом — она грузится лениво."""

    def get(self, request, *args, **kwargs):
        if not request.htmx:
            return redirect(reverse_lazy('products'))
        filterset = ProductFilter(request.GET, queryset=_base_queryset())
        filterset.build_helper(url=reverse_lazy('products'))
        return render(request, 'product/partials/filter.html', {'filter': filterset})


class ProductSuppliersView(View):
    """Строки поставщиков под товаром.

    Отдельным запросом, а не join-ом в основную выборку: поставщиков у товара
    единицы, а товаров на странице десятки, и тянуть их всегда — платить за то,
    что почти никто не раскроет.
    """

    def get(self, request, pk, *args, **kwargs):
        product = get_object_or_404(Product, pk=pk)
        main_products = (
            MainProduct.objects.filter(product=product)
            .select_related('supplier', 'supplier__currency')
            .annotate(**_latest_supplier_prices())
            .order_by('supplier__name', 'article')
        )
        table = SupplierRowTable(main_products, request=request,
                                 selected_columns=load_columns(request.user))
        return render(request, 'product/partials/suppliers.html', {
            'product': product,
            'main_products': main_products,
            'table': table,
        })


def _latest_supplier_prices():
    """Цены из последней по времени строки прайса поставщика.

    Колонки «Цена поставщика», «РРЦ» и «Цена поставщика со скидкой» — не поля
    MainProduct, а SupplierProduct. Старая главная брала их так же:
    подзапросом к самой свежей строке. Аннотируются всегда, а не только когда
    колонка выбрана: строк поставщиков под товаром единицы, и три подзапроса
    на них дешевле, чем ветвление по выбору.
    """
    latest = SupplierProduct.objects.filter(main_product=OuterRef('pk')).order_by('-updated_at')
    return {
        'supplier_product_price': Subquery(latest.values('supplier_price')[:1]),
        'supplier_product_rrp': Subquery(latest.values('rrp')[:1]),
        'supplier_product_discount_price': Subquery(latest.values('discount_price')[:1]),
    }


class PimImageView(View):
    """Фото из PIM через нас — браузеру PIM без токена отвечает 401.

    Доступ — как у любой страницы приложения: LoginRequiredMiddleware. Байты
    кэшируются на сутки на сервере (fetch_pim_image) и в браузере
    (Cache-Control: private — картинка отдана залогиненному пользователю, в
    общих кэшах ей делать нечего).
    """

    def get(self, request, file_id, size):
        image = fetch_pim_image(file_id, size)
        if image is None:
            raise Http404
        content, content_type = image
        response = HttpResponse(content, content_type=content_type)
        response['Cache-Control'] = 'private, max-age=86400'
        return response
