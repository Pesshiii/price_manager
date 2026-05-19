from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
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
    name = models.CharField('Название', max_length=255, unique=True)
    slug = models.SlugField('Слаг', max_length=255, unique=True)

    class Meta:
        verbose_name = 'Бренд'
        verbose_name_plural = 'Бренды'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True) or 'brand'
            slug = base
            i = 2
            while Brand.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{i}'
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class CharacteristicType(models.Model):
    VALUE_STRING = 'string'
    VALUE_INTEGER = 'integer'
    VALUE_FLOAT = 'float'
    VALUE_BOOLEAN = 'boolean'
    VALUE_CHOICE = 'choice'
    VALUE_TYPE_CHOICES = [
        (VALUE_STRING, 'Строка'),
        (VALUE_INTEGER, 'Целое число'),
        (VALUE_FLOAT, 'Число'),
        (VALUE_BOOLEAN, 'Да/Нет'),
        (VALUE_CHOICE, 'Выбор из списка'),
    ]

    name = models.SlugField('Ключ', max_length=64, unique=True, allow_unicode=True)
    label = models.CharField('Название', max_length=255)
    value_type = models.CharField('Тип значения', max_length=16, choices=VALUE_TYPE_CHOICES, default=VALUE_STRING)
    options = models.JSONField('Варианты', default=list, blank=True)
    unit = models.CharField('Единица измерения', max_length=32, blank=True)
    required = models.BooleanField('Обязательная', default=False)
    categories = models.ManyToManyField(
        Category,
        related_name='characteristic_types',
        blank=True,
        verbose_name='Категории',
    )

    class Meta:
        verbose_name = 'Тип характеристики'
        verbose_name_plural = 'Типы характеристик'
        ordering = ['label']

    def __str__(self) -> str:
        return self.label or self.name

    def validate_value(self, raw):
        """Coerce raw value to the declared type. Raise ValidationError on failure.

        Returns the coerced value to be stored in the product's JSON.
        """
        if raw is None or raw == '':
            if self.required:
                raise ValidationError(f"'{self.name}' обязательна.")
            return None

        vt = self.value_type
        try:
            if vt == self.VALUE_STRING:
                return str(raw)
            if vt == self.VALUE_INTEGER:
                if isinstance(raw, bool):
                    raise ValueError
                return int(raw)
            if vt == self.VALUE_FLOAT:
                if isinstance(raw, bool):
                    raise ValueError
                return float(raw)
            if vt == self.VALUE_BOOLEAN:
                if isinstance(raw, bool):
                    return raw
                s = str(raw).strip().lower()
                if s in ('1', 'true', 'да', 'yes', 'y'):
                    return True
                if s in ('0', 'false', 'нет', 'no', 'n'):
                    return False
                raise ValueError
            if vt == self.VALUE_CHOICE:
                value = str(raw)
                if self.options and value not in self.options:
                    raise ValidationError(
                        f"'{self.name}': значение '{value}' не входит в допустимые ({', '.join(self.options)})."
                    )
                return value
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"'{self.name}': невалидное значение '{raw}' для типа {vt}.") from exc

        raise ValidationError(f"'{self.name}': неизвестный тип значения {vt}.")


class Product(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Черновик'),
        (STATUS_ACTIVE, 'Активный'),
        (STATUS_ARCHIVED, 'В архиве'),
    ]

    sku = models.CharField('Артикул', max_length=128, unique=True, db_index=True)
    name = models.CharField('Название', max_length=512, db_index=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='products',
        verbose_name='Категория',
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='products',
        verbose_name='Бренд',
    )
    description = models.TextField('Описание', blank=True)
    status = models.CharField('Статус', max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    characteristics = models.JSONField('Характеристики', default=dict, blank=True)
    image_urls = models.JSONField('Изображения', default=list, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['-updated_at']
        indexes = [
            GinIndex(fields=['characteristics'], name='product_chars_gin_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.sku} — {self.name}'

    def clean(self):
        chars = self.characteristics or {}
        if not isinstance(chars, dict):
            raise ValidationError({'characteristics': 'Должен быть JSON-объект.'})

        types_by_name = {
            ct.name: ct
            for ct in CharacteristicType.objects.filter(name__in=list(chars.keys()))
        }
        cleaned = {}
        errors = {}
        for key, raw in chars.items():
            ct = types_by_name.get(key)
            if ct is None:
                errors[key] = f"Неизвестная характеристика '{key}'."
                continue
            try:
                value = ct.validate_value(raw)
            except ValidationError as exc:
                errors[key] = exc.messages[0] if exc.messages else str(exc)
                continue
            if value is not None:
                cleaned[key] = value

        if self.category_id is not None:
            required_types = CharacteristicType.objects.filter(
                required=True,
                categories=self.category_id,
            )
            for ct in required_types:
                if cleaned.get(ct.name) in (None, ''):
                    errors[ct.name] = f"Характеристика '{ct.name}' обязательна для категории."

        if errors:
            raise ValidationError(
                {'characteristics': [f'{key}: {msg}' for key, msg in errors.items()]}
            )

        self.characteristics = cleaned


class ImportJob(models.Model):
    KIND_PREVIEW = 'preview'
    KIND_COMMIT = 'commit'
    KIND_CHOICES = [(KIND_PREVIEW, 'Preview'), (KIND_COMMIT, 'Commit')]

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_ERROR, 'Error'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='product_import_jobs',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    stage = models.CharField(max_length=64, blank=True, default='')
    session_id = models.CharField(max_length=64)
    instructions = models.JSONField(default=dict, blank=True)
    mapping = models.JSONField(default=dict, blank=True)
    row_limit = models.PositiveIntegerField(default=200)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
