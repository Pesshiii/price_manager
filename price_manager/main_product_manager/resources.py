from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from .models import *
from supplier_manager.models import Discount

class MainProductWidget(ForeignKeyWidget):
    """Главный продукт по артикулу и поставщику."""

    def clean(self, value, row=None, *args, **kwargs):
        if not value:
            return None
        supplier_name = row.get("supplier", "").strip()
        if not supplier_name:
            return None
        name = row.get("name", "").strip()
        if not name:
            return None
        supplier, _ = Supplier.objects.get_or_create(name=supplier_name)
        main_product, _ = MainProduct.objects.get_or_create(
            article=value,
            supplier=supplier,
            name=name,
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
    # Производитель, группа и описание — только на выгрузку и из PIM (Product):
    # собственные manufacturer, categories и description у MainProduct удалены
    # в Phase 2b. Колонки и их заголовки прежние, чтобы не сломать тех, кто
    # грузит этот файл дальше; на импорт они больше не принимаются — писать
    # их некуда.
    manufacturer = fields.Field(column_name="Производитель")
    category = fields.Field(column_name="Название_группы")
    supplier_prices = fields.Field(column_name='Supplier Prices')
    m_price = fields.Field(
        column_name="Цена",
        attribute="m_price")
    stock = fields.Field(
        column_name="Количество",
        attribute="stock")
    description = fields.Field(column_name='HTML_описание')


    class Meta:
        model = MainProduct
        
        # Отдельно поля для экспорта и импорта
        export_fields = (
            "id",
            "sku",
            "supplier",
            "article",
            "name",
            "description",
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
            "stock",
            "prime_cost",
            "basic_price",
            "m_price"
        )

        # Какие реально использовать при каждой операции
        fields = export_fields
        export_order = export_fields
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True

    def export(self, queryset=None, **kwargs):
        # Колонки ходят в product, его бренд и категории и в строки прайса —
        # без предзагрузки это несколько запросов на каждую из ~160 тыс. строк.
        if queryset is None:
            queryset = self.get_queryset()
        from django.db.models import Prefetch
        from product.filters import CATEGORY_LABEL_DEPTH
        from product.models import Category as ProductCategory

        queryset = queryset.select_related('supplier', 'product__brand').prefetch_related(
            Prefetch('product__categories',
                     queryset=ProductCategory.objects.select_related(CATEGORY_LABEL_DEPTH)),
            'supplierproducts__supplier__currency',
        )
        return super().export(queryset, **kwargs)

    def dehydrate_manufacturer(self, mainproduct):
        product = mainproduct.product
        return product.brand.name if product and product.brand else ""

    def dehydrate_category(self, mainproduct):
        """Путь первой категории товара: 'Инструмент > Ручной инструмент'."""
        product = mainproduct.product
        # .all()[0], а не .first(): first() добавляет ORDER BY и обходит
        # предзагрузку. Путь — по уже загруженной цепочке parent.
        categories = list(product.categories.all()) if product else []
        if not categories:
            return ""
        path, node = [], categories[0]
        while node is not None:
            path.append(node.name)
            node = node.parent
        return " > ".join(reversed(path))

    def dehydrate_description(self, mainproduct):
        product = mainproduct.product
        return (product.raw_data or {}).get('description') or "" if product else ""

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
