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
    
    
class MainProductWidget(ForeignKeyWidget):
    """Главный продукт по артикулу и поставщику."""

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        supplier_name = row.get("supplier", "").strip()
        if not supplier_name:
            return None
        supplier, _ = Supplier.objects.get_or_create(name=supplier_name)
        main_product, _ = MainProduct.objects.get_or_create(
            article=value,
            supplier=supplier,
        )
        return main_product
    def render(self, value, obj=None, **kwargs):
        if not value:
            return ""
        return value.article
    
class SupplierWidget(ForeignKeyWidget):
    """Поставщик по названию."""

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        supplier, _ = Supplier.objects.get_or_create(name=value)
        return supplier
    
class ManufacturerWidget(ForeignKeyWidget):
    """Производитель по названию."""

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        manufacturer, _ = Manufacturer.objects.get_or_create(name=value)
        return manufacturer

class DiscountWidget(ManyToManyWidget):
    """Скидки по названию."""

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return Discount.objects.none()
        names = [v.strip() for v in str(value).split(",") if v and str(v).strip()]
        discounts = []
        for name in names:
            discount, _ = Discount.objects.get_or_create(name=name)
            discounts.append(discount)
        return discounts

class MainProductResource(resources.ModelResource):
    # читаемые колонки для FKs
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
    supplier_prices = fields.Field(column_name='Supplier Prices')
    

    class Meta:
        model = MainProduct
        
        # Отдельно поля для экспорта и импорта
        export_fields = (
            "id",
            "sku",
            "supplier",
            "article",
            "name",
            "category",
            "manufacturer",
            "stock",
            "prime_cost",
            "wholesale_price",
            "basic_price",
            "m_price",
            "supplier_prices",
        )

        import_fields = (
            "sku",
            "supplier",
            "article",
            "name",
            "category",
            "manufacturer",
            "stock",
            "prime_cost",
            "basic_price",
        )

        # Какие реально использовать при каждой операции
        fields = export_fields
        export_order = export_fields
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True

    def dehydrate_supplier_prices(self, mainproduct):
        """
        Format all supplier prices for this main product.
        Поддерживает разные варианты названий связи.
        """

        # 1) FK-вариант (если связь одиночная)
        sp_fk = getattr(mainproduct, "supplier_product", None)
        if sp_fk is not None and not hasattr(sp_fk, "all"):
            sp_list = [sp_fk] if sp_fk else []

        else:
            # 2) ManyToMany / reverse FK варианты (если связь множественная)
            rel = (
                    getattr(mainproduct, "supplier_products", None) or
                    getattr(mainproduct, "supplier_product", None) or
                    getattr(mainproduct, "supplierpricerow_set", None) or
                    getattr(mainproduct, "supplierproduct_set", None)
            )

            if rel is None:
                return ""

            sp_list = list(rel.all())

        if not sp_list:
            return ""

        price_list = []
        for sp in sp_list:
            supplier_name = getattr(getattr(sp, "supplier", None), "name", "") or ""
            supplier_price = getattr(sp, "supplier_price", "") or ""
            rrp = getattr(sp, "rrp", "") or ""
            currency = getattr(getattr(getattr(sp, "supplier", None), "currency", None), "name", "") or getattr(
                getattr(sp, "supplier", None), "currency", "") or ""

            price_list.append(f"{supplier_name}: {supplier_price}({rrp}) {currency}".strip())

        return " | ".join([p for p in price_list if p])

    def get_import_fields(self, selected_fields=None):
        """Ограничить набор импортируемых полей"""
        return [self.fields[f] for f in self.Meta.import_fields]

    def get_export_fields(self, selected_fields=None):
        """Ограничить набор экспортируемых полей"""
        return [self.fields[f] for f in self.Meta.export_fields]
