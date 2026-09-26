from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from django.db.models import Value
from django.db.models.functions import Lower
from django.utils.text import slugify
from mptt.models import MPTTModel, TreeForeignKey


class Category(MPTTModel):
    parent = TreeForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='children',
        null=True,
        blank=True,
        verbose_name='Родительская категория',
    )
    name = models.CharField('Название', max_length=255)
    slug = models.SlugField('Слаг', max_length=255, unique=True)
    pim_id = models.CharField(
        'Id категории в PIM', max_length=64, null=True, blank=True, unique=True,
    )

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        constraints = [
            models.UniqueConstraint(fields=['parent', 'name'], name='product_category_parent_name_uniq'),
        ]

    class MPTTMeta:
        order_insertion_by = ['name']

    def __str__(self) -> str:
        return f'{self.parent}>{self.name}' if self.parent_id else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True) or 'category'
            slug = base
            i = 2
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Brand(models.Model):
    """Бренд из PIM. Ключ — brandId, как его отдаёт PIM.

    Словаря вариаций написания намеренно нет (D3): brandId из PIM — ссылка на
    сущность, и дубль написания здесь — это дубль СУЩНОСТИ в PIM, а не
    вариация текста. Такие есть (R5, 2026-09-21: 14 групп вида STAYER/Stayer
    на 321 бренд); их сливают в PIM, а не склеивают здесь. Бывший
    supplier_manager.ManufacturerDict решал похожую задачу для названий от
    поставщиков, не использовался (0 строк на проде) и удалён в Phase 2b-3.
    """

    pim_id = models.CharField('Id бренда в PIM', max_length=64, unique=True)
    name = models.CharField('Название', max_length=255)

    class Meta:
        verbose_name = 'Бренд'
        verbose_name_plural = 'Бренды'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


# Основные цены Product из прайса поставщика: поле Product -> поле SupplierProduct.
SUPPLIER_PRICE_FIELDS = {
    'supplier_price': 'supplier_price',
    'rrp': 'rrp',
    'supplier_discount_price': 'discount_price',
}


class Product(models.Model):
    # Id of this Product's PriceManagerProduct in PIM — the through record whose
    # platformID is our pk and whose productId points at the PIM Product. NULL
    # until reindex_pim_ids pushes it.
    pim_id = models.CharField(
        'Id связи в PIM (PriceManagerProduct)', max_length=64, null=True, blank=True, unique=True,
    )
    # The match key: MainProduct.sku. Local, never overwritten from PIM.
    # Case-insensitive: uniqueness is enforced by Meta.constraints on
    # Lower('number'), not by unique=True here — see the product_product_number_lower_uniq
    # constraint below.
    number = models.CharField('Артикул', max_length=128, null=True, blank=True)
    # Not unique: several Products can sit on one PIM Product, and PIM does not
    # keep Product.name unique either.
    name = models.CharField('Название', max_length=512, null=True, blank=True)
    categories = models.ManyToManyField(
        Category, related_name='products', blank=True, verbose_name='Категории',
    )
    brand = models.ForeignKey(
        Brand,
        related_name='products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Бренд',
    )
    raw_data = models.JSONField('Сырые данные PIM', default=dict, blank=True)
    # Основные цены товара — те же семь, что у MainProduct (MP_PRICES), сведённые
    # по строкам поставщиков так же, как в экспорте: верхний уровень
    # Supplier.price_priority, на уровне — поставщик с минимальной
    # себестоимостью, у него первая ненулевая (services/prices.py). Пишет только
    # services/prices.recalculate_base_prices, руками не правятся. Это исходные
    # цены для наценок product_pricing; расчётные цены лежат там, в ProductPrice.
    prime_cost = models.DecimalField('Себестоимость', max_digits=20, decimal_places=2, null=True, blank=True)
    wholesale_price = models.DecimalField('Оптовая цена', max_digits=20, decimal_places=2, null=True, blank=True)
    basic_price = models.DecimalField('Базовая цена', max_digits=20, decimal_places=2, null=True, blank=True)
    m_price = models.DecimalField('Цена ИМ', max_digits=20, decimal_places=2, null=True, blank=True)
    wholesale_price_extra = models.DecimalField(
        'Оптовая цена доп.', max_digits=20, decimal_places=2, null=True, blank=True)
    discount_price = models.DecimalField('Цена со скидкой', max_digits=20, decimal_places=2, null=True, blank=True)
    kaspi_price = models.DecimalField('Цена Каспи', max_digits=20, decimal_places=2, null=True, blank=True)
    # Цены из прайса поставщика (SupplierProduct, SP_PRICES), переведённые в
    # тенге по курсу валюты поставщика — тем же выбором поставщика, что и цены
    # выше. Ключ: SUPPLIER_PRICE_FIELDS.
    supplier_price = models.DecimalField(
        'Цена поставщика, тг', max_digits=20, decimal_places=2, null=True, blank=True)
    rrp = models.DecimalField('РРЦ, тг', max_digits=20, decimal_places=2, null=True, blank=True)
    supplier_discount_price = models.DecimalField(
        'Цена поставщика со скидкой, тг', max_digits=20, decimal_places=2, null=True, blank=True)
    prices_updated_at = models.DateTimeField('Цены пересчитаны', null=True, blank=True)
    search_vector = SearchVectorField('Вектор поиска', null=True, editable=False)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['-updated_at']
        indexes = [
            GinIndex(fields=['search_vector'], name='product_search_vector_gin'),
        ]
        constraints = [
            models.UniqueConstraint(Lower('number'), name='product_product_number_lower_uniq'),
        ]

    def __str__(self) -> str:
        return f'{self.number} — {self.name}'

    @property
    def display_name(self) -> str:
        """Название для показа.

        `name` приходит из PIM и пуст у каждой строки, которую засеяла миграция
        0005 и которую ещё не синхронизировали (154 969 строк на проде на
        2026-09-03). Пустая ячейка в таблице — это не «нет названия», а «ещё не
        сходили в PIM», поэтому откатываемся на название любого из связанных
        MainProduct: его заполняет прайс поставщика, и оно есть всегда.
        """
        if self.name:
            return self.name
        main_product = self.main_products.first()
        return main_product.name if main_product else (self.number or self.pim_id)

    def _build_searchvector(self) -> SearchVector:
        """Вектор поиска строится ТОЛЬКО из локальных данных.

        Никаких обращений к PIM: всё, что нужно, уже лежит в raw_data, который
        пишет sync_product_from_pim. Это главное отличие от
        MainProduct._build_searchvector(), который ходил в сеть прямо из метода
        модели и делал это на каждое сохранение.

        Разделитель — пробел, а не ''. В MainProduct стояло ''.join(...), из-за
        чего названия категорий склеивались в один токен («ДушКабины» вместо
        «Душ» + «Кабины») и по отдельному слову категория не находилась.
        """
        data = self.raw_data or {}
        # Без данных PIM — локальные название, бренд и категории: их правят
        # руками на карточке товара (product/forms.ProductForm), и такой товар
        # должен находиться по тому, что ему вписали.
        categories = ' '.join((data.get('categoriesNames') or {}).values())
        if not data and self.pk:
            categories = ' '.join(self.categories.values_list('name', flat=True))
        brand_name = data.get('brandName') or (self.brand.name if self.brand_id else '')
        tags = ' '.join(data.get('tag') or [])
        return (
            SearchVector(Value(categories), weight='A', config='russian') +
            SearchVector(Value(tags), weight='A', config='russian') +
            SearchVector(Value(data.get('name') or self.name or ''), weight='A', config='russian') +
            SearchVector(Value(self.number or ''), weight='B', config='russian') +
            SearchVector(Value(brand_name), weight='B', config='russian') +
            SearchVector(Value(data.get('description') or ''), weight='C', config='russian') +
            SearchVector(Value(data.get('longDescription') or ''), weight='C', config='russian')
        )

    def rebuild_search_vector(self) -> None:
        """Пересобирает search_vector через update() — без join-полей в SET."""
        Product.objects.filter(pk=self.pk).update(search_vector=self._build_searchvector())


class ProductSetItem(models.Model):
    """Одна позиция состава набора — зеркало ассоциации PIM «Состав набора».

    Набор — это Product, у которого есть такие строки; отдельного флага нет.
    Свои поставщики у набора могут быть (собранный на складе, со своей ценой),
    а могут и не быть; себестоимость «из комплектующих» считается по составу
    в любом случае, рядом с собственной.
    Заполняет только sync_product_sets (services/sets.py), руками не правится.

    Компонент хранится дважды: ссылкой на наш Product и снимком из PIM (id,
    артикул, название). Снимок нужен потому, что компонента у нас может не
    быть вовсе — товар PIM, который ни один поставщик не продаёт, — а состав
    всё равно должен показать его, иначе неполный набор выглядел бы полным и
    его себестоимость — правдой. По той же причине component — SET_NULL, а не
    CASCADE: удаление Product-компонента не должно тихо укорачивать набор,
    строка остаётся «не найден», а следующая синхронизация найдёт его заново.
    """

    set_product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='set_items', verbose_name='Набор',
    )
    component = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='in_sets', verbose_name='Компонент',
    )
    # Ключ позиции внутри набора: id товара PIM, а не наш Product — его может не быть.
    component_pim_product_id = models.CharField('Id компонента в PIM (Product)', max_length=64)
    component_number = models.CharField('Артикул компонента в PIM', max_length=128, blank=True, default='')
    component_name = models.CharField('Название компонента в PIM', max_length=512, blank=True, default='')
    amount = models.PositiveIntegerField('Количество', default=1)
    sorting = models.IntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Позиция набора'
        verbose_name_plural = 'Состав наборов'
        ordering = ['sorting', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['set_product', 'component_pim_product_id'],
                name='product_setitem_set_component_uniq',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.set_product_id}: {self.component_number or self.component_pim_product_id} × {self.amount}'


class ProductExport(models.Model):
    """Готовый файл экспорта товарной страницы; ссылка приходит в уведомлении."""

    user = models.ForeignKey(
        'auth.User',
        verbose_name='Пользователь',
        on_delete=models.CASCADE,
        related_name='product_exports')
    file = models.FileField(
        verbose_name='Файл',
        upload_to='product_exports/',
        null=True,
        blank=True)
    rows_count = models.PositiveIntegerField(verbose_name='Строк', default=0)
    created_at = models.DateTimeField(verbose_name='Создан', auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Экспорт товаров'
        verbose_name_plural = 'Экспорты товаров'

    def __str__(self):
        return f'Экспорт товаров — {self.created_at:%d.%m.%Y %H:%M}'
