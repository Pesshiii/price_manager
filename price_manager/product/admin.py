from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path
from django.views.decorators.http import require_POST
from mptt.admin import DraggableMPTTAdmin

from .models import Category, Product, ProductSetItem
from .tasks import export_products_full_csv_task


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    list_display = ('tree_actions', 'indented_title', 'slug', 'pim_id')
    search_fields = ('name', 'slug', 'pim_id')


class ProductSetItemInline(admin.TabularInline):
    """Состав набора. Только чтение: его пересобирает sync_product_sets из PIM,
    и ручная правка пропала бы на следующем прогоне."""
    model = ProductSetItem
    fk_name = 'set_product'
    extra = 0
    can_delete = False
    fields = ('component', 'component_number', 'component_name', 'amount', 'sorting')
    readonly_fields = fields
    verbose_name_plural = 'Состав набора'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = (ProductSetItemInline,)
    list_display = ('number', 'name', 'pim_id',  'updated_at')
    search_fields = ('number', 'name', 'pim_id')
    filter_horizontal = ('categories',)
    readonly_fields = ('raw_data', 'created_at', 'updated_at')
    # Кнопка «Полный экспорт (csv)» над списком.
    change_list_template = 'admin/product/product/change_list.html'

    def get_urls(self):
        return [
            path('export-full-csv/',
                 self.admin_site.admin_view(require_POST(self.export_full_csv_view)),
                 name='product_product_export_full_csv'),
        ] + super().get_urls()

    def export_full_csv_view(self, request):
        """Ставит полный csv-экспорт в очередь; файл — по ссылке в оповещениях сайта.

        Весь каталог, фильтры и поиск списка не учитываются. POST — запуск
        минутной задачи не должен случаться от перехода по ссылке.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        export_products_full_csv_task.delay(user_id=request.user.pk)
        self.message_user(
            request,
            'Полный экспорт запущен. Ссылка на файл придёт в оповещениях на сайте.',
            messages.INFO)
        return redirect('admin:product_product_changelist')
