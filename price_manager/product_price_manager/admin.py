from django.contrib import admin
from .models import PriceManager, UniquePriceManager

@admin.register(PriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    # form = PriceManagerAdminForm
    list_display = ['id', 'name', 'supplier', 'display_discounts']
    # autocomplete_fields = []  # можешь оставить пустым; если захочешь, подключим позже
    # def get_form(self, request, obj=None, **kwargs):
    #     """
    #     Передаём объект request в форму, чтобы она могла читать supplier из GET/POST.
    #     """
    #     Form = super().get_form(request, obj, **kwargs)
    #     class RequestAwareForm(Form):
    #         def __init__(self2, *args, **kw):
    #             kw['request'] = request
    #             super().__init__(*args, **kw)
    #     return RequestAwareForm
    def display_discounts(self, obj):
        return ", ".join([discount.name for discount in obj.discounts.all()])
    display_discounts.short_description = 'Категории Скидок'

@admin.register(UniquePriceManager)
class PriceManagerAdmin(admin.ModelAdmin):
    # form = PriceManagerAdminForm
    list_display = ['id', 'main_products_display', 'source', 'dest', 'markup', 'increase']
    # autocomplete_fields = []  # можешь оставить пустым; если захочешь, подключим позже
    # def get_form(self, request, obj=None, **kwargs):
    #     """
    #     Передаём объект request в форму, чтобы она могла читать supplier из GET/POST.
    #     """
    #     Form = super().get_form(request, obj, **kwargs)
    #     class RequestAwareForm(Form):
    #         def __init__(self2, *args, **kw):
    #             kw['request'] = request
    #             super().__init__(*args, **kw)
    #     return RequestAwareForm
    def main_products_display(self, obj):
        return ", ".join([mp.name for mp in obj.main_products.all()])
    main_products_display.short_description = 'Товары главного прайса'
