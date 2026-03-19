from django.apps import AppConfig


class SupplierProductManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'supplier_product_manager'

    def ready(self):
        import supplier_product_manager.signals  # noqa: F401
