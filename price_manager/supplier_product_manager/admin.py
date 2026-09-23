from django.contrib import admin
from .models import ImportRun, SupplierProduct, SupplierFile, Setting
from .functions import resolve_conflicts

@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    # показываем все поля модели
    list_display = [field.name for field in SupplierProduct._meta.fields]
    # делаем кликабельным поле name (или id, если удобнее)
    list_display_links = ['id', 'name']
    search_fields = ['article', 'name', 'stock']
    list_filter = ['supplier']
    actions = ['resolve_conflicts']
    
    @admin.action(description="Разрешить конфликты форматирования")
    def resolve_conflicts(self, request, queryset):
        resolve_conflicts(queryset)

@admin.register(SupplierFile)
class SupplierFileAdmin(admin.ModelAdmin):
    # показываем все поля модели
    list_display = ['pk', 'setting', 'status', 'logs']


@admin.register(Setting)
class SupplierFileAdmin(admin.ModelAdmin):
    # показываем все поля модели
    list_display = ['pk', 'name']


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    # История только для чтения: её пишет задача импорта.
    list_display = ['started_at', 'setting', 'supplier', 'status',
                    'covered', 'covered_price', 'covered_stock', 'created', 'missing', 'missing_linked']
    list_filter = ['status', 'supplier']
    list_select_related = ['setting', 'supplier']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False