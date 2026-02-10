from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from difflib import get_close_matches
from .models import *
from supplier_manager.models import ManufacturerDict

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
        normalized_name = str(value).strip()
        if not normalized_name:
            return None

        # 1) Точное совпадение по имени производителя
        manufacturer = Manufacturer.objects.filter(name__iexact=normalized_name).first()
        if manufacturer:
            return manufacturer

        # 2) Сопоставление через словарь вариаций производителя
        manufacturer_dict = ManufacturerDict.objects.filter(
            name__iexact=normalized_name
        ).select_related("manufacturer").first()
        if manufacturer_dict:
            return manufacturer_dict.manufacturer

        # 3) Пытаемся сопоставить с уже существующим производителем
        existing_names = list(Manufacturer.objects.values_list("name", flat=True))
        close_matches = get_close_matches(normalized_name, existing_names, n=1, cutoff=0.85)
        if close_matches:
            manufacturer = Manufacturer.objects.get(name=close_matches[0])
            ManufacturerDict.objects.get_or_create(
                name=normalized_name,
                defaults={"manufacturer": manufacturer},
            )
            return manufacturer

        # 4) Если сопоставить не удалось — создаём нового производителя
        return Manufacturer.objects.create(name=normalized_name)

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
        """Format all supplier prices for this main product"""
        supplierproducts = mainproduct.supplierproducts.all()
        if not supplierproducts:
            return "No suppliers"
        
        price_list = []
        for sp in supplierproducts:
            price_list.append(f"{sp.supplier.name}: {sp.supplier_price}({sp.rrp}) {sp.supplier.currency}")
        
        return " | ".join(price_list)

    def get_import_fields(self, selected_fields=None):
        """Ограничить набор импортируемых полей"""
        return [self.fields[f] for f in self.Meta.import_fields]

    def get_export_fields(self, selected_fields=None):
        """Ограничить набор экспортируемых полей"""
        return [self.fields[f] for f in self.Meta.export_fields]
