from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from .models import *

class CategoryWidget(ForeignKeyWidget):
    """Категория строкой: 'Инструмент > Ручной инструмент > Отвертки'."""

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        parts = [p.strip() for p in str(value).split(">") if p and str(p).strip()]
        parent = None
        node = None
        for name in parts[:10]:
            node, _ = Category.objects.get_or_create(name=name, parent=parent)
            parent = node
        return node

    def render(self, value, obj=None, **kwargs):
        if not value:
            return ""
        path = []
        cur = value
        while cur:
            path.append(cur.name)
            cur = cur.parent
        return " > ".join(reversed(path))


class MainProductResource(resources.ModelResource):
    # читаемые колонки для FKs
    supplier = fields.Field(
        column_name="supplier",
        attribute="supplier",
        widget=ForeignKeyWidget(Supplier, "name"),
    )
    manufacturer = fields.Field(
        column_name="manufacturer",
        attribute="manufacturer",
        widget=ForeignKeyWidget(Manufacturer, "name"),
    )
    category = fields.Field(
        column_name="category",
        attribute="category",
        widget=CategoryWidget(Category, "name"),
    )

    class Meta:
        model = MainProduct
        # Экспортируем ВСЕ поля модели
        fields = tuple(f.name for f in MainProduct._meta.fields)
        export_order = fields
        # Импортируем c сопоставлением по ID
        import_id_fields = ("id",)
        skip_unchanged = True
        skip_errors = True
        report_skipped = True

class SupplierProductResource(resources.ModelResource):
    supplier = fields.Field(
        column_name="supplier",
        attribute="supplier",
        widget=ForeignKeyWidget(Supplier, "name"),
    )
    manufacturer = fields.Field(
        column_name="manufacturer",
        attribute="manufacturer",
        widget=ForeignKeyWidget(Manufacturer, "name"),
    )
    category = fields.Field(
        column_name="category",
        attribute="category",
        widget=CategoryWidget(Category, "name"),
    )
    discounts = fields.Field(
        column_name="discounts",
        attribute="discounts",
        widget=ManyToManyWidget(Discount, field="name", separator=", "),
    )

    class Meta:
        model = SupplierProduct
        fields = tuple(f.name for f in SupplierProduct._meta.fields) + ("discounts",)
        export_order = fields
        import_id_fields = ("id",)
        skip_unchanged = True
        skip_errors = True
        report_skipped = True