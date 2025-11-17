from django.apps import AppConfig


class PriceManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'price_manager_app'
    label = 'price_manager'
    verbose_name = 'Менеджер цен'
