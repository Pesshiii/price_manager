from django.shortcuts import render

from django_filters.views import FilterView

from .models import Product
# Create your views here.

class MainPage(FilterView):
  model = MainProduct
  filterset_class = MainProductFilter
  template_name = 'mainproduct/list.html'
  def get_template_names(self) -> list[str]:
      if self.request.htmx:
        if not self.request.GET.get('page', 1) == 1:
          return ["mainproduct/partials/tables_bycat.html#category-table"]
        return ["mainproduct/partials/tables_bycat.html"]
      return super().get_template_names()
  def get_filterset_kwargs(self, filterset_class):
      kwargs = super().get_filterset_kwargs(filterset_class)
      # Add your custom kwarg here
      kwargs['url'] = reverse_lazy('mainproducts')
      if not self.request.htmx:
        kwargs['bound_ignore']=True
      return kwargs
  def get_context_data(self, **kwargs) -> dict[str, Any]:
    context = super().get_context_data(**kwargs)
    queryset = context['object_list']
    categories = Paginator(
        Category.objects.filter(
        pk__in=queryset.prefetch_related('category').values_list('category__pk')
      ).prefetch_related(
        'mainproducts'
      ).annotate(
        mps_count=Count(F('mainproducts'))
      ).filter(~Q(mps_count=0)),
      5
    ).page(self.request.GET.get('page', 1))
    context['categories'] =  categories
    context['has_nulled'] = queryset.filter(category__isnull=True).exists()
    context['nulled_mp_count'] = queryset.filter(category__isnull=True).count()
    context['column_groups'] = AVAILABLE_COLUMN_GROUPS
    selected_columns = self.request.GET.getlist('columns')
    if selected_columns:
      selected_columns = save_user_columns(self.request.user, selected_columns)
    if not selected_columns:
        selected_columns = load_user_columns(self.request.user)
    if not selected_columns:
        selected_columns = DEFAULT_VISIBLE_COLUMNS
    context['selected_columns'] = selected_columns if selected_columns else DEFAULT_VISIBLE_COLUMNS
    return context
  def render_to_response(self, context, **response_kwargs):
    response = super().render_to_response(context, **response_kwargs)
    if self.request.htmx and self.request.GET.get('page', 1) == 1:
      response['Hx-Push'] = self.request.get_full_path()
    return response
  

class List(FilterView):
   model=Product