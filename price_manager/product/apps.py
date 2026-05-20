from django.apps import AppConfig


class ProductConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'product'
    verbose_name = 'Товары'

    def ready(self):
        from . import signals  # noqa: F401
