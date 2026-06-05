from django.apps import AppConfig


class TransformConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'transform'
    verbose_name = 'Трансформации'

    def ready(self):
        import transform.signals  # noqa: F401
