from django.apps import AppConfig


class DataframeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dataframe'
    verbose_name = 'Dataframe'

    def ready(self):
        from . import functions  # noqa: F401  register readers/transforms
