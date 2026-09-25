import logging
import os

from django.contrib import messages
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.http import FileResponse, Http404, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import DetailView, UpdateView, View
from django_filters.views import FilterView
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh, trigger_client_event
from django_tables2 import SingleTableMixin

from core.task_runner import dispatch_after_commit
from main_product_manager.models import MP_PRICES, MainProduct
from main_product_manager.utils import fetch_pim_image, pim_image_url
from product_pricing.models import ProductPrice
from product_pricing.services import product_price_rows
from product_pricing.tasks import update_product_prices_task
from supplier_product_manager.models import SupplierProduct

from .columns import PRODUCT_COLUMN_GROUPS, load_columns, save_columns
from .filters import CATEGORY_LABEL_DEPTH, ProductFilter, matching_product_pks, ranked, search_terms
from .forms import ProductForm
from .models import SUPPLIER_PRICE_FIELDS, Category, Product, ProductExport
from .services.prices import BASE_PRICE_FIELDS, recalculate_base_prices
from .set_costs import attach_set_info, set_totals_for
from .tasks import export_products_task
from .tables import (
    ProductTable, SupplierRowTable, annotate_product_rows, best_match_groups_first,
    category_path, primary_category, with_category_headers,
)

logger = logging.getLogger(__name__)

# Событие «выдача товаров сменилась»; его слушает #product-facets-refresh
# в product/list.html.
PRODUCTS_UPDATED_EVENT = 'products-updated'


def _base_queryset(by_category=False):
    """Товары для страницы.

    select_related('brand') и prefetch категорий — ячейка названия выводит под
    ним бренд и категории (ProductTable.render_display_name) на каждой строке,
    без этого страница даёт N+1 на обеих связях. Категории предзагружаются
    вместе с предками: из них строится путь в заголовке группы
    (tables.category_path), и без select_related каждый шаг к корню был бы
    запросом. Расчётные цены (product_pricing) — тоже предзагрузкой, с
    правилом: колонки цен (tables.ProductPriceColumn) и подсказка с именем
    наценки читают их на каждой строке.
    """
    categories = Category.objects.select_related(CATEGORY_LABEL_DEPTH)
    prices = ProductPrice.objects.select_related('rule')
    return annotate_product_rows(
        Product.objects.select_related('brand')
        .prefetch_related(Prefetch('categories', queryset=categories),
                          Prefetch('prices', queryset=prices)),
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

    def render_to_response(self, context, **response_kwargs):
        """HTMX-ответ таблицы сообщает странице, что выдача сменилась.

        На это событие панель перезапрашивает фасеты (ProductFacetsView). Шлём
        его на любой HTMX-ответ, а не только на фильтр и поиск: пагинация и
        сортировка здесь — обычные ссылки, а лишнее обновление фасетов после
        выбора колонок безвредно.
        """
        response = super().render_to_response(context, **response_kwargs)
        if self.request.htmx:
            trigger_client_event(response, PRODUCTS_UPDATED_EVENT)
        return response

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
        # Наборы и компоненты — только для показанных строк; ячейки таблицы
        # отрисовываются в шаблоне позже и читают навешенное здесь.
        attach_set_info(row.record for _, row in context['product_rows'])
        return context


class ProductFilterView(View):
    """Отдаёт панель фильтров отдельным запросом — она грузится лениво."""

    def get(self, request, *args, **kwargs):
        if not request.htmx:
            return redirect(reverse_lazy('products'))
        filterset = ProductFilter(request.GET, queryset=_base_queryset())
        filterset.narrow_facets()
        filterset.build_helper(url=reverse_lazy('products'))
        return render(request, 'product/partials/filter.html', {'filter': filterset})


class ProductFacetsView(View):
    """Списки фасетов под текущую выдачу — OOB-фрагментами, без панели.

    Зовётся событием PRODUCTS_UPDATED_EVENT после каждого ответа таблицы, а не
    встроен в сам ответ: три агрегата по всем товарам не должны задерживать
    выдачу — таблица приходит сразу, фасеты догоняют.
    """

    def get(self, request, *args, **kwargs):
        if not request.htmx:
            return redirect(reverse_lazy('products'))
        filterset = ProductFilter(request.GET, queryset=Product.objects.all())
        filterset.narrow_facets()
        filterset.build_facets_helper()
        return render(request, 'product/partials/facets.html', {'filter': filterset})


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
            # Набор: под своими строками — строка «Из комплектующих» и состав.
            'set_totals': set_totals_for([product.pk]).get(product.pk),
            # Цены самого товара: основные и расчётные по наценкам.
            'base_prices': [
                (Product._meta.get_field(field).verbose_name, getattr(product, field))
                for field in BASE_PRICE_FIELDS if getattr(product, field)
            ],
            'calculated_prices': ProductPrice.objects.filter(product=product)
            .select_related('price_type', 'rule').order_by('price_type__sorting', 'price_type__name'),
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


class ProductExportView(View):
    """Ставит экспорт текущей выдачи в очередь.

    query — строка запроса страницы из адресной строки: поиск и фильтр
    пушат её через hx-push-url, сортировка — обычные ссылки, так что в ней
    всё, чем задана выдача. Номер страницы выкидывается — выгружается вся
    выдача. Колонки — сохранённый выбор (его сохраняет сама страница при
    каждой смене), экспорт его не пересохраняет.

    Ответ пустой: toaster_middleware сам покажет сообщение тостом, а
    перезагрузка сбила бы раскрытые строки и прокрутку. Именно 200, а не
    204: на 204 HTMX не доходит до settle, а тост запрашивается событием
    toasts:fetch после settle — сообщение молча осталось бы в сессии до
    следующей страницы.
    """

    def post(self, request, *args, **kwargs):
        params = QueryDict(request.POST.get('query', '').lstrip('?'), mutable=True)
        params.pop(ProductTable._meta.prefix + ProductTable._meta.page_field, None)
        params.pop('columns', None)
        export_products_task.delay(query=params.urlencode(),
                                   columns=load_columns(request.user),
                                   user_id=request.user.pk)
        messages.info(request, 'Экспорт запущен. Ссылка на файл придёт в уведомлениях.')
        return HttpResponse()


class ProductExportDownloadView(View):
    """Отдаёт готовый файл экспорта — только тому, кто его запускал."""

    def get(self, request, pk, *args, **kwargs):
        export = get_object_or_404(ProductExport, pk=pk, user=request.user)
        if not export.file:
            raise Http404('Файл выгрузки не найден')
        # Расширение — с диска: там и xlsx страницы, и полный csv из админки.
        extension = os.path.splitext(export.file.name)[1] or '.xlsx'
        return FileResponse(export.file.open('rb'), as_attachment=True,
                            filename=f'Товары {export.created_at:%Y-%m-%d %H-%M}{extension}')


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


# --- карточка товара ---------------------------------------------------------

def _price_list(product, fields):
    return [(Product._meta.get_field(field).verbose_name, getattr(product, field))
            for field in fields if getattr(product, field)]


class ProductDetailView(DetailView):
    """Карточка товара: цены (расчётные и основные), строки ГП, состав набора.

    Отсюда же правка и удаление товара, перенос строк ГП и наценка на этот
    товар — всё модалками в #modal-container, успех перезагружает карточку.
    """

    model = Product
    template_name = 'product/detail.html'
    context_object_name = 'product'

    def get_queryset(self):
        categories = Category.objects.select_related(CATEGORY_LABEL_DEPTH)
        return Product.objects.select_related('brand').prefetch_related(
            Prefetch('categories', queryset=categories))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.object
        main_products = list(
            MainProduct.objects.filter(product=product)
            .select_related('supplier', 'supplier__currency')
            .annotate(**_latest_supplier_prices())
            .order_by('supplier__name', 'article'))
        category = primary_category(product)
        data = product.raw_data or {}
        context.update({
            'main_products': main_products,
            'category_path': category_path(category) if category else [],
            'price_rows': product_price_rows(product),
            'gp_prices': _price_list(product, MP_PRICES),
            'pp_prices': _price_list(product, SUPPLIER_PRICE_FIELDS),
            'set_totals': set_totals_for([product.pk]).get(product.pk),
            'in_sets': Product.objects.filter(set_items__component=product).distinct().order_by('name'),
            'photo_url': pim_image_url(data.get('mainImageId') or data.get('imageId')),
        })
        return context


class ProductUpdateView(UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'product/partials/product_form.html'

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Товар сохранён')
        return HttpResponseClientRefresh()


class ProductDeleteView(View):
    """Удаление товара — только без строк ГП.

    Строка ГП без товара ночью снова привязывается к товару с артикулом = её
    sku (link_unlinked_main_products), и если его нет, он создаётся заново:
    удалённый вместе со строками товар вернулся бы сам. Поэтому сначала
    строки переносят в другие товары, потом удаляют.
    """

    template_name = 'product/partials/product_delete.html'

    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        return render(request, self.template_name, {
            'product': product,
            'main_products_count': product.main_products.count(),
            'prices_count': product.prices.count(),
            'set_items_count': product.set_items.count(),
        })

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        if product.main_products.exists():
            messages.error(request, 'У товара есть строки ГП — перенесите их в другие товары')
            return HttpResponseClientRefresh()
        name = product.display_name
        product.delete()
        messages.success(request, f'Товар «{name}» удалён')
        return HttpResponseClientRedirect(reverse_lazy('products'))


def _relinked(request, main_product, target, message):
    """Перенос строки ГП в другой товар и пересчёт цен обоих.

    Основные цены двух товаров пересчитываются сразу — это дёшево, и карточка
    после перезагрузки уже верна; расчётные — общим пересчётом после коммита.
    Связь, поставленная руками, ночью не трогается: link_unlinked_main_products
    привязывает только строки без товара.
    """
    source_pk = main_product.product_id
    with transaction.atomic():
        main_product.product = target
        main_product.save(update_fields=['product'])
        recalculate_base_prices(pks=[pk for pk in (source_pk, target.pk) if pk])
        dispatch_after_commit(update_product_prices_task)
    messages.success(request, message)
    return HttpResponseClientRefresh()


SEARCH_LIMIT = 12


class MainProductAttachView(View):
    """«Привязать строку ГП»: поиск строк ГП и перенос выбранной в этот товар.

    Строка забирается из товара, где она была, — у строки ГП товар один.
    """

    template_name = 'product/partials/attach_main_product.html'

    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        query = request.GET.get('q', '').strip()
        results = []
        if query:
            condition = Q()
            for term in search_terms(query):
                condition &= Q(sku__icontains=term) | Q(article__icontains=term) | Q(name__icontains=term)
            results = list(MainProduct.objects.filter(condition).exclude(product=product)
                           .select_related('supplier', 'product').order_by('sku', 'pk')[:SEARCH_LIMIT])
        template = self.template_name + '#results' if 'q' in request.GET else self.template_name
        return render(request, template, {'product': product, 'query': query, 'results': results,
                                          'limit': SEARCH_LIMIT})

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        main_product = get_object_or_404(MainProduct, pk=request.POST.get('main_product'))
        return _relinked(request, main_product, product,
                         f'Строка ГП «{main_product.name}» привязана к товару')


class MainProductMoveView(View):
    """«Перенести в другой товар»: поиск товара и перенос строки ГП в него."""

    template_name = 'product/partials/move_main_product.html'

    def get(self, request, pk):
        main_product = get_object_or_404(MainProduct.objects.select_related('supplier', 'product'), pk=pk)
        query = request.GET.get('q', '').strip()
        results = []
        if query:
            results = list(ranked(
                Product.objects.filter(pk__in=matching_product_pks(query))
                .exclude(pk=main_product.product_id).select_related('brand'),
                query)[:SEARCH_LIMIT])
        template = self.template_name + '#results' if 'q' in request.GET else self.template_name
        return render(request, template, {'main_product': main_product, 'query': query,
                                          'results': results, 'limit': SEARCH_LIMIT})

    def post(self, request, pk):
        main_product = get_object_or_404(MainProduct, pk=pk)
        target = get_object_or_404(Product, pk=request.POST.get('product'))
        return _relinked(request, main_product, target,
                         f'Строка ГП перенесена в товар «{target.display_name}»')
