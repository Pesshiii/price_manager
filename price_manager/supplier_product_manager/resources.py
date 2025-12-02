from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from .models import *
from core.resources import MainProductWidget, SupplierWidget, ManufacturerWidget, CategoryWidget, DiscountWidget

class SupplierProductResource(resources.ModelResource):
    main_product = fields.Field(
        column_name="main_product",
        attribute="main_product",
        widget=MainProductWidget(MainProduct, "article"),
    )
    supplier = fields.Field(
        column_name="supplier",
        attribute="supplier",
        widget=SupplierWidget(Supplier, "name"),
    )
    manufacturer = fields.Field(
        column_name="manufacturer",
        attribute="manufacturer",
        widget=ManufacturerWidget(Manufacturer, "name"),
    )
    category = fields.Field(
        column_name="category",
        attribute="category",
        widget=CategoryWidget(Category, "name"),
    )
    discounts = fields.Field(
        column_name="discounts",
        attribute="discounts",
        widget=DiscountWidget(Discount, "name"),
    )

    class Meta:
        model = SupplierProduct
        
        # Отдельно поля для экспорта и импорта
        export_fields = (
            "main_product",
            "supplier",
            "article",
            "name",
            "category",
            "discounts",
            "manufacturer",
            "stock",
            "supplier_price",
            "rrp",
        )
        import_fields = (
            "main_product",
            "supplier",
            "article",
            "name",
            "category",
            "discounts",
            "manufacturer",
            "stock",
            "supplier_price",
            "rrp",
        )

        # Какие реально использовать при каждой операции
        fields = export_fields
        export_order = export_fields
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
    
    def get_import_fields(self):
        """Ограничить набор импортируемых полей"""
        return [self.fields[f] for f in self.Meta.import_fields]

    def get_export_fields(self):
        """Ограничить набор экспортируемых полей"""
        return [self.fields[f] for f in self.Meta.export_fields]
