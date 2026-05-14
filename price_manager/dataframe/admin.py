from django.contrib import admin

from .models import Dataframe


@admin.register(Dataframe)
class DataframeAdmin(admin.ModelAdmin):
    list_display = ('name', 'updated_at')
    search_fields = ('name',)
