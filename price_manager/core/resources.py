from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import MainProduct, Supplier, Manufacturer, Category


class MainProductResource(resources.ModelResource):
    supplier = fields.Field(
        column_name='supplier',
        attribute='supplier',
        widget=ForeignKeyWidget(Supplier, field='name')
    )
    manufacturer = fields.Field(
        column_name='manufacturer',
        attribute='manufacturer',
        widget=ForeignKeyWidget(Manufacturer, field='name')
    )
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(Category, field='name')
    )

    class Meta:
        model = MainProduct
        fields = [f.name for f in MainProduct._meta.fields]
        export_order = fields
        import_id_fields = ['id']
        skip_unchanged = True
        report_skipped = True

    def skip_row(self, instance, original):
        """
        Пропускаем строки, у которых нет ID (чтобы не создавать новые товары).
        """
        return instance.id is None
