from django_filters import filters, FilterSet
from django import forms
from django.db.models import Exists, OuterRef, Q, Case, When, Value, IntegerField

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Field, Div, HTML, Hidden
from core.crispy_fields import OobField

from product.filters import (
  CATEGORY_LABEL_DEPTH,
  category_with_descendants,
  expanded_category_pks,
  matching_product_pks,
  ranked,
  search_terms,
  selected_values,
)
from product.models import Brand, Category, Product
from supplier_manager.models import Supplier

from .models import MainProduct


class MainProductFilter(FilterSet):
  """Выбор строк поставщиков: корзина (товары к элементу корзины, автоподбор
  при импорте) и «Привязать из ГП» в карточке товара.

  Корень выборки — MainProduct, а не Product, и это правильно именно здесь:
  покупают у конкретного поставщика, так что строка = предложение поставщика.
  Но поиск и контентные фасеты (категории, бренд) идут через MainProduct.product
  — туда, где они живут после переноса. Собственные search_vector, categories
  и manufacturer у MainProduct уходят в Phase 2 (см.
  .claude/shift-to-product-brief.md), и этот фильтр не должен от них зависеть.

  Строки без привязки к Product (product IS NULL) по-прежнему находятся: поиск
  дополнительно смотрит на собственные sku / name / article. На товарной
  странице такие строки невидимы (D5), но здесь невидимость означала бы
  «нельзя купить», а на это решения не было.
  """
  class Meta:
    model = MainProduct
    fields = ['search', 'categories', 'brand', 'supplier', 'available']

  search = filters.CharFilter(
    method='search_method',
    label='Поиск товаров',
    widget=forms.TextInput(
       attrs={
          'placeholder': 'Название, артикул или ключевое слово',
          'class': 'form-control',
       }
    )
  )

  available = filters.BooleanFilter(
    label='Товары в наличии',
    method='available_method',
    widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
  )

  supplier = filters.ModelMultipleChoiceFilter(
    label='Поставщики',
    field_name='supplier',
    queryset=Supplier.objects.none(),
    widget=forms.widgets.CheckboxSelectMultiple(
      attrs={'class':'form-check'},
    )
    )

  brand = filters.ModelMultipleChoiceFilter(
    label='Бренды',
    method='brand_method',
    queryset=Brand.objects.none(),
    widget=forms.widgets.CheckboxSelectMultiple(
      attrs={'class':'form-check'},
    )
    )

  categories = filters.ModelMultipleChoiceFilter(
    queryset=Category.objects.none(),
    widget=forms.CheckboxSelectMultiple(),
    method='categories_method',
    label='Категории'
  )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.config_filters(self.search_method(self.queryset, '', value=self.data.get('search', '')))

  def build_helper(self, url, hx_target: str | None = '#mainproducts-table', stripped=False):
    """Builds the crispy FormHelper/Layout for rendering the filter form.

    Only needed by a view that actually renders mainproduct/partials/filter.html
    (CartItemProductSelectView, ResolveMainproduct) — other callers only need
    `.qs`, so this is kept out of __init__ to avoid paying for it on every
    filterset instantiation.

    `stripped=True` renders just the filter fields with no <form> tag, header, or
    submit button — used by ResolveMainproduct when re-embedding the form inside an
    htmx-swapped table fragment that must stay bound to the same GET params.
    """
    helper = FormHelper(self.form)
    helper.form_id = 'mainproduct-filter'
    helper.form_method = 'GET'
    helper.label_class = 'mt-2'
    helper.attrs = {
      'hx-get':url,
      'hx-swap':'outerHTML',
      'hx-trigger':'input changed delay:2s, change delay:2s, submit',
      'hx-push-url':'true',
      'hx-include':'#mainproducts-search',
    }
    if hx_target:
      helper.attrs['hx-target']=hx_target
    if stripped:
      helper.form_tag = False
      helper.layout = Layout(
          OobField('categories', template='product/partials/category_tree_field.html'),
          OobField('supplier', template='core/includes/checkbox_field.html#checkboxes'),
          OobField('brand', template='core/includes/checkbox_field.html#checkboxes'),)
    else:
      helper.layout = Layout(
          Hidden('bound', 'true'),
          HTML('''
            <div class="filter-header d-flex align-items-center gap-2 mb-3">
              <i class="bi bi-sliders text-primary"></i>
              <h5 class="mb-0">Фильтры товаров</h5>
            </div>
          '''),
          Div(
            Field('available', template='core/includes/switch_field.html'),
            css_class='filter-section'
          ),
          Div(
            Field('categories', template='product/partials/category_tree_field.html'),
            css_class='filter-section'
          ),
          Div(
            Field('supplier', template='core/includes/checkbox_field.html'),
            css_class='filter-section'
          ),
          Div(
            Field('brand', template='core/includes/checkbox_field.html'),
            css_class='filter-section filter-section-last'
          ),
          Div(
            Submit('action', 'Применить', title="Применить", css_class='btn btn-primary flex-grow-1'),
            HTML(f"""<a href=\"{url}\" class=\"btn btn-outline-secondary\" title=\"Сбросить\"><i class="bi bi-arrow-counterclockwise"></i></a>"""),
            HTML('''<button type="button" class="btn btn-outline-secondary" id="filter-scroll-top-btn" title="Наверх" data-ignore-auto-update="true"><i class="bi bi-arrow-up"></i></button>'''),
            css_class='d-flex gap-2 filter-actions'
          )
      )
    self.form.helper = helper
    return helper

  def _selected_ids(self, name):
    """Выбранные pk фасета — только числа.

    Фасеты собираются в __init__, ДО валидации формы, так что мусор из
    адресной строки уронил бы pk__in с ValueError, а не просто не выбрался бы.
    """
    return [pk for pk in selected_values(self.data, name) if str(pk).isdigit()]

  @staticmethod
  def _selected_first(queryset, selected):
    """Фасет из того, что есть в выдаче, плюс уже выбранное — выбранное наверху.

    Выбранное подмешивается обратно: иначе фильтр, сузивший выдачу до нуля,
    выкинул бы собственную галочку из списка, и снять её стало бы нечем.
    """
    if not selected:
      return queryset.order_by('name')
    return queryset.model.objects.filter(
      Q(pk__in=queryset) | Q(pk__in=selected)
    ).annotate(
      is_selected=Case(
        When(pk__in=selected, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
      )
    ).order_by('is_selected', 'name')

  def config_filters(self, queryset):
    """Фасеты сужаются под поиск: ищут «молоток» — видят поставщиков и бренды
    молотков, а не весь справочник."""
    self.filters['supplier'].field.queryset = self._selected_first(
      Supplier.objects.filter(pk__in=queryset.values('supplier')),
      self._selected_ids('supplier'),
    )
    self.filters['brand'].field.queryset = self._selected_first(
      Brand.objects.filter(pk__in=queryset.values('product__brand')),
      self._selected_ids('brand'),
    )

    # Предки берутся у объединения «встречается в выдаче» + «выбрано», а не
    # только у первого. Дерево рисует {% recursetree %}, и выбранный узел без
    # своих предков он принимает за корень; если следом по дереву идёт узел
    # мельче уровнем, mptt падает с «not in depth-first order» — модалка
    # корзины отдаёт 500. Так бывает, когда поиск исключил товары выбранной
    # категории: её предков в выдаче больше нет.
    category_queryset = Category.objects.filter(
      Q(pk__in=queryset.values('product__categories'))
      | Q(pk__in=self._selected_ids('categories'))
    ).get_ancestors(include_self=True)
    # select_related — см. CATEGORY_LABEL_DEPTH.
    self.filters['categories'].field.queryset = category_queryset.select_related(CATEGORY_LABEL_DEPTH)
    # Раскрытые ветки — см. expanded_category_pks: шаблон дерева их не считает.
    self.filters['categories'].field.expanded_pks = expanded_category_pks(
      self._selected_ids('categories'))

  def search_method(self, queryset, name, value):
    """Поиск по товару (Product) ИЛИ по собственным полям строки.

    Первая ветка — ровно поиск товарной страницы (matching_product_pks): вектор
    Product, его номер, название у любого поставщика этого товара. Вторая —
    sku / name / article самой строки: артикул поставщика важен именно при
    покупке, и только так находятся строки без привязки к Product.

    UNION, а не OR — по той же причине, что и в matching_product_pks: под OR
    Postgres теряет индексный план и проходит таблицу целиком.
    """
    terms = search_terms(value)
    if not terms:
      return queryset
    own_fields = Q()
    for term in terms:
      own_fields &= Q(sku__icontains=term) | Q(name__icontains=term) | Q(article__icontains=term)
    matched = (
      MainProduct.objects.filter(product_id__in=matching_product_pks(value)).values('pk')
      .union(MainProduct.objects.filter(own_fields).values('pk'))
    )
    return ranked(queryset.filter(pk__in=matched), value, vector='product__search_vector')

  def available_method(self, queryset, name, value):
    if value:
      return queryset.filter(stock__gt=0)
    return queryset

  def brand_method(self, queryset, name, value):
    if not value:
      return queryset
    return queryset.filter(product__brand__in=value)

  def categories_method(self, queryset, name, value):
    """Exists, а не product__categories__in: товар в двух выбранных категориях
    дал бы строку дважды, а distinct() убил бы сортировку по рангу."""
    if not value:
      return queryset
    return queryset.filter(
      Exists(Product.categories.through.objects.filter(
        product_id=OuterRef('product_id'),
        category_id__in=category_with_descendants(value),
      ))
    )
