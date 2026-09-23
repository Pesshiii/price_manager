from django.db import models
from django.core.validators import FileExtensionValidator
from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from main_product_manager.models import MainProduct
from supplier_manager.models import Supplier, Discount

from decimal import Decimal
  
SP_TABLE_FIELDS = ['article', 'name', 'supplier_price', 'rrp', 'discount', ]
SP_PRICES = ['supplier_price', 'rrp', 'discount_price']
SP_NUMBERS = ['supplier_price', 'rrp', 'stock', 'discount_price']

class SupplierProduct(models.Model):
  pim_id = models.CharField(verbose_name='Id для системы Pim',
                            null=True,
                            blank=True)
  # unique=True (not OneToOneField) so `related_name='supplierproducts'` keeps
  # working as a manager everywhere it's used (dehydrate_supplier_prices,
  # get_sprice, update_stocks, ...) while still enforcing one MainProduct per
  # SupplierProduct at the DB level.
  main_product=models.ForeignKey(MainProduct,
                        verbose_name='sku',
                        related_name='supplierproducts',
                        on_delete=models.SET_NULL,
                        null=True,
                        blank=True,
                        unique=True)
  supplier=models.ForeignKey(Supplier,
                             verbose_name='Поставщик',
                             related_name='supplierproducts',
                             on_delete=models.CASCADE,
                             null=False,
                             blank=False)
  article = models.CharField(verbose_name='Артикул поставщика',
                             null=False,
                             blank=False)
  name = models.CharField(verbose_name='Название',
                          null=False,
                          blank=False)
  description = models.TextField(
    verbose_name="Описание",
    null=True,
    blank=True)
  discount = models.ForeignKey(Discount,
                                verbose_name='Группа скидок',
                                related_name='supplierproducts',
                                on_delete=models.SET_NULL,
                                null=True,
                                blank=True)
  stock = models.PositiveIntegerField(verbose_name='Остаток',
      null=True,
      blank=True)
  supplier_price = models.DecimalField(
      verbose_name='Цена поставщика в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True,
      blank=True)
  rrp = models.DecimalField(
      verbose_name='РРЦ в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True,
      blank=True)
  discount_price = models.DecimalField(
      verbose_name='Цена со скидкой в валюте поставщика',
      decimal_places=2,
      max_digits=20,
      null=True,
      blank=True)
  updated_at = models.DateTimeField(verbose_name='Последнее обновление',
                                    auto_now=True,
      blank=True)
  # Settings whose latest import contained this row. An import clears the
  # fields its setting maps only on rows linked to that setting, and unlinks
  # them as it does — so a row moved to another file of the same supplier is
  # cleared once, not on every import of the old setting.
  source_settings = models.ManyToManyField('Setting',
                                           verbose_name='Поставляют настройки',
                                           related_name='supplied_products',
                                           blank=True)
  class Meta:
    constraints = [
      models.UniqueConstraint(
        fields=['supplier', 'article', 'name'],
        name='sp_uniqe_supplier_article_name'
      )
    ]

# Модели для менджмента загрузки/обновления поставщиков

# Базовые данные
LINKS = {'': 'Не включать',
         'article': 'Артикул поставщика',
         'name': 'Название',
         'description': 'Описание',
         'discount': 'Группа скидок',
         'stock': 'Остаток',
         'supplier_price': 'Цена поставщика в валюте поставщика',
         'rrp': 'РРЦ в валюте поставщика',
         'discount_price': 'Цена со скидкой в валюте поставщика',
         }

class Setting(models.Model):
  name = models.CharField(verbose_name='Название',
                          unique=False,
                          null=False)
  supplier = models.ForeignKey(Supplier,
                               related_name='settings',
                              on_delete=models.CASCADE,
                              blank=False)
  sheet_name = models.CharField(verbose_name='Название листа')
  # Identity of a supplier row is (article, name) by default: many suppliers sell
  # variants under one article. For a supplier whose articles are unique, the
  # article alone identifies the row — a new name in the file renames it instead
  # of creating a second product. Replaced ignore_name (0014).
  match_by_article = models.BooleanField(
    verbose_name='Артикул уникален — сопоставлять только по артикулу',
    default=False)
  create_new = models.BooleanField(verbose_name='Создавать если нет',
                                   default=False)
  index_row = models.IntegerField(verbose_name='Ряд для индексации',
                                   null=True, blank=True)
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='name_supplier_constraint')]
  def __str__(self):
    return self.name
  def clearable_fields(self) -> list[str]:
    """Остаток и цены, которые настройка сопоставляет — только их она очищает."""
    mapped = (self.links.filter(key__in=['stock', *SP_PRICES])
              .filter(models.Q(value__isnull=False) & ~models.Q(value='')
                      | models.Q(initial__isnull=False) & ~models.Q(initial=''))
              .values_list('key', flat=True))
    return sorted(set(mapped))

  def is_bound(self) -> bool:
    for link in self.links.filter(value=''):
      link.value = None
      link.save()
    if not self.links.filter(key='article', value__isnull=False).exists():
      return False
    if self.create_new and not self.links.filter(key='name', value__isnull=False):
      return False
    return True

class Link(models.Model):
  class Meta:
    constraints = [models.UniqueConstraint(fields=['setting', 'key'], name='link-field-constraint')]
  setting = models.ForeignKey(Setting,
                              on_delete=models.CASCADE,
                              related_name='links')
  initial = models.CharField(null=True)
  key = models.CharField(choices=LINKS)
  value = models.CharField(null=True)
  def __str__(self):
    return f'{self.key}<--->{self.value}({self.initial})'
  

class DictItem(models.Model):
  link = models.ForeignKey(Link,
                           on_delete=models.CASCADE,
                           verbose_name='Столбец',
                           related_name='dicts',
                           blank=True,
                           null=True)
  key = models.CharField(verbose_name='Если')
  value = models.CharField(verbose_name='То')
  class Meta:
    constraints = [models.UniqueConstraint(fields=['link', 'key', 'value'], name='link-dict-constraint')]

def setting_dir(instance, filename):
  return f'setting_{instance.setting.supplier.pk}/{filename}'

class SupplierFile(models.Model):
  STATUS_QUEUED = 0
  STATUS_RUNNING = 2
  STATUS_SUCCESS = 1
  STATUS_ERROR = -1
  STATUS_NEEDS_CONFIRMATION = 3

  STATUS_CHOICES = [
    (STATUS_QUEUED, 'В очереди'),
    (STATUS_RUNNING, 'В процессе'),
    (STATUS_SUCCESS, 'Успешно'),
    (STATUS_ERROR, 'Ошибка'),
    (STATUS_NEEDS_CONFIRMATION, 'Ждёт подтверждения'),
  ]

  setting = models.ForeignKey(Setting,
                              null=True,
                              blank=True,
                              verbose_name="Настройка",
                              related_name="supplierfiles",
                              on_delete=models.CASCADE)
  file = models.FileField(verbose_name='Файл',
                          upload_to=setting_dir,
                          max_length=255,
                          validators=[FileExtensionValidator(allowed_extensions=['xls', 'xlsx', 'xlsm'])],
                          null=False)
  status = models.IntegerField(verbose_name="Статус загрузки",
                               choices=STATUS_CHOICES,
                               default=STATUS_QUEUED,
                               blank=True)
  logs = models.CharField(verbose_name="Журнал загрузки", null=True, blank=True)


@receiver(pre_delete, sender=SupplierFile)
def document_pre_delete(sender, instance, **kwargs):
    """Clean up file before model deletion"""
    instance.file.delete(save=False)


@receiver(pre_delete, sender=Setting)
def release_supplied_products(sender, instance, **kwargs):
    """Удаляемая настройка очищает свои поля у товаров, которые поставляла только она.

    Иначе их остаток и цены застыли бы навсегда: ни одна настройка их больше
    не обновит и не очистит. Пустой остаток безопаснее застывшего. Товары,
    которые поставляет и другая настройка, не трогаются. Сигнал, а не код во
    вьюхе: настройку удаляют и с её экрана, и из админки, и вместе с поставщиком.
    """
    fields = instance.clearable_fields()
    if not fields:
        return
    SupplierProduct.objects.filter(source_settings=instance).exclude(
        source_settings__in=Setting.objects.exclude(pk=instance.pk),
    ).update(**{field: None for field in fields})


def format_count(value) -> str:
  """1234567 -> «1 234 567» (узкий неразрывный пробел)."""
  return f"{int(value):,}".replace(",", " ")


def _rows_word(value) -> str:
  """1 строка, 2 строки, 5 строк, 21 строка, 11 строк."""
  value = abs(int(value))
  if value % 10 == 1 and value % 100 != 11:
    return "строка"
  if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
    return "строки"
  return "строк"


class ImportRun(models.Model):
  """Один запуск импорта прайса по настройке и его счётчики.

  История покрытия настройки: по ней проверка импорта сравнивает новый файл с
  обычным для этой настройки числом строк — отдельно с ценой и с остатком.
  Счётчики разбора — см. functions.SPS_STAT_FIELDS. created/updated/missing
  есть у применённого импорта и у ждущего подтверждения (там — что сделает
  применение); у отказа их нет.
  """
  STATUS_RUNNING = "running"
  STATUS_APPLIED = "applied"
  STATUS_REFUSED = "refused"
  STATUS_FAILED = "failed"
  STATUS_NEEDS_CONFIRMATION = "pending"
  STATUS_CANCELLED = "cancelled"
  STATUS_SUPERSEDED = "superseded"

  STATUS_CHOICES = [
    (STATUS_RUNNING, "Выполняется"),
    (STATUS_APPLIED, "Применён"),
    (STATUS_REFUSED, "Отказ"),
    (STATUS_FAILED, "Ошибка"),
    (STATUS_NEEDS_CONFIRMATION, "Ждёт подтверждения"),
    (STATUS_CANCELLED, "Отменён"),
    (STATUS_SUPERSEDED, "Заменён"),
  ]

  setting = models.ForeignKey(Setting,
                              verbose_name="Настройка",
                              related_name="import_runs",
                              on_delete=models.CASCADE)
  supplier = models.ForeignKey(Supplier,
                               verbose_name="Поставщик",
                               related_name="import_runs",
                               on_delete=models.CASCADE)
  # SET_NULL: the cleanup task deletes old files, the history must outlive them.
  supplier_file = models.ForeignKey(SupplierFile,
                                    verbose_name="Файл",
                                    related_name="import_runs",
                                    on_delete=models.SET_NULL,
                                    null=True, blank=True)
  file_name = models.CharField(verbose_name="Имя файла", max_length=255, blank=True, default="")
  user = models.ForeignKey(settings.AUTH_USER_MODEL,
                           verbose_name="Пользователь",
                           related_name="import_runs",
                           on_delete=models.SET_NULL,
                           null=True, blank=True)
  status = models.CharField(verbose_name="Статус",
                            max_length=16,
                            choices=STATUS_CHOICES,
                            default=STATUS_RUNNING)
  message = models.TextField(verbose_name="Сообщение", blank=True, default="")
  started_at = models.DateTimeField(verbose_name="Начало", auto_now_add=True)
  finished_at = models.DateTimeField(verbose_name="Окончание", null=True, blank=True)
  mapped_keys = models.JSONField(verbose_name="Сопоставленные поля", default=list, blank=True)
  # Setting + file signature at the time of the check: a confirmation applies
  # only the file and mapping the user was shown.
  signature = models.CharField(verbose_name="Сигнатура настройки", max_length=64, blank=True, default="")
  guard_reasons = models.JSONField(verbose_name="Причины проверки", default=list, blank=True)
  confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   verbose_name="Подтвердил",
                                   related_name="confirmed_import_runs",
                                   on_delete=models.SET_NULL,
                                   null=True, blank=True)
  confirmed_at = models.DateTimeField(verbose_name="Подтверждён", null=True, blank=True)

  rows_in_sheet = models.PositiveIntegerField(verbose_name="Строк на листе", null=True, blank=True)
  rows_with_article = models.PositiveIntegerField(verbose_name="Строк с артикулом", null=True, blank=True)
  rows_with_values = models.PositiveIntegerField(verbose_name="Строк со значениями", null=True, blank=True)
  rows_without_name = models.PositiveIntegerField(verbose_name="Отброшено без названия", null=True, blank=True)
  rows_unmatched = models.PositiveIntegerField(verbose_name="Не совпало с товарами", null=True, blank=True)
  duplicates = models.PositiveIntegerField(verbose_name="Дубликатов", null=True, blank=True)
  article_conflicts = models.PositiveIntegerField(verbose_name="Артикулов с разными названиями",
                                                  null=True, blank=True)
  renamed = models.PositiveIntegerField(verbose_name="Переименовано", null=True, blank=True)
  articles_multi_db = models.PositiveIntegerField(verbose_name="Артикулов с несколькими товарами в базе",
                                                  null=True, blank=True)
  covered = models.PositiveIntegerField(verbose_name="Покрыто строк", null=True, blank=True)
  covered_price = models.PositiveIntegerField(verbose_name="Покрыто с ценой", null=True, blank=True)
  covered_stock = models.PositiveIntegerField(verbose_name="Покрыто с остатком", null=True, blank=True)
  created = models.PositiveIntegerField(verbose_name="Создано", null=True, blank=True)
  updated = models.PositiveIntegerField(verbose_name="Обновлено", null=True, blank=True)
  missing = models.PositiveIntegerField(verbose_name="Нет в файле (обнулено)", null=True, blank=True)
  missing_linked = models.PositiveIntegerField(verbose_name="Из них привязаны к ГП", null=True, blank=True)
  # functions.price_changes: how the file changes the prices of existing rows,
  # per price field. Recorded only, the guard does not act on it yet.
  price_changes = models.JSONField(verbose_name="Изменения цен", default=dict, blank=True)

  COUNTER_FIELDS = (
    "rows_in_sheet", "rows_with_article", "rows_with_values", "rows_without_name",
    "rows_unmatched", "duplicates", "article_conflicts", "renamed", "articles_multi_db",
    "covered", "covered_price", "covered_stock",
    "created", "updated", "missing", "missing_linked",
  )

  class Meta:
    ordering = ("-started_at",)
    indexes = [models.Index(fields=["setting", "status", "-started_at"], name="importrun_setting_history")]
    verbose_name = "Импорт прайса"
    verbose_name_plural = "Импорты прайсов"

  def __str__(self):
    return f"{self.setting} · {self.get_status_display()} · {self.started_at:%Y-%m-%d %H:%M}"

  GUARD_METRIC_LABELS = {"covered_price": "С ценой", "covered_stock": "С остатком"}
  PRICE_FIELD_LABELS = {"supplier_price": "Цена поставщика", "rrp": "РРЦ", "discount_price": "Цена со скидкой"}

  def reason_lines(self) -> list[str]:
    """Причины, по которым импорт ждёт подтверждения, — по строке на причину."""
    lines = []
    for reason in self.guard_reasons:
      if reason.get("kind") == "history":
        lines.append(
          f"Первые загрузки этой настройки: история ещё копится "
          f"({reason['have']} из {reason['need']})")
      elif reason.get("kind") == "drop":
        label = self.GUARD_METRIC_LABELS.get(reason["metric"], reason["metric"])
        lines.append(f"{label}: {format_count(reason['value'])} {_rows_word(reason['value'])}, "
                     f"обычно ~{format_count(reason['baseline'])}")
      elif reason.get("kind") == "missing_linked":
        lines.append(f"Нет в файле {format_count(reason['value'])} {_rows_word(reason['value'])}, "
                     f"привязанных к ГП, из {format_count(reason['linked'])}: "
                     f"у товаров каталога обнулятся {self._cleared_words()}")
    return lines

  def _cleared_words(self) -> str:
    stock = "stock" in self.mapped_keys
    prices = any(key in self.mapped_keys for key in SP_PRICES)
    return "остаток и цены" if stock and prices else "остаток" if stock else "цены"

  def price_change_lines(self) -> list[tuple[str, str]]:
    """«Разбор файла»: как меняются цены строк, которые уже есть в базе."""
    lines = []
    for column, change in self.price_changes.items():
      label = self.PRICE_FIELD_LABELS.get(column, column)
      lines.append((f"{label}: изменилась", f"{format_count(change['changed'])} из {format_count(change['compared'])}"))
      lines.append((f"{label}: больше чем в 2 раза", format_count(change['jumps'])))
    return lines

  def record_stats(self, stats: dict) -> None:
    """Перенести известные счётчики и mapped_keys из stats, лишние ключи игнорируются."""
    for name in self.COUNTER_FIELDS:
      if name in stats:
        setattr(self, name, stats[name])
    if "mapped_keys" in stats:
      self.mapped_keys = list(stats["mapped_keys"])
    if "price_changes" in stats:
      self.price_changes = dict(stats["price_changes"])


class CopySupplierProductsToMainRun(models.Model):
  STATUS_STARTED = "started"
  STATUS_SUCCESS = "success"
  STATUS_ERROR = "error"

  STATUS_CHOICES = [
    (STATUS_STARTED, "Выполняется"),
    (STATUS_SUCCESS, "Успешно"),
    (STATUS_ERROR, "Ошибка"),
  ]

  supplier = models.ForeignKey(
    Supplier,
    verbose_name="Поставщик",
    related_name="copy_to_main_runs",
    on_delete=models.CASCADE,
  )
  user = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    verbose_name="Пользователь",
    related_name="copy_to_main_runs",
    on_delete=models.CASCADE,
  )
  status = models.CharField(
    verbose_name="Статус",
    max_length=16,
    choices=STATUS_CHOICES,
    default=STATUS_STARTED,
    db_index=True,
  )
  filter_params = models.JSONField(verbose_name="Параметры фильтра", default=dict, blank=True)
  processed_count = models.PositiveIntegerField(verbose_name="Обработано записей", default=0)
  created_count = models.PositiveIntegerField(verbose_name="Создано новых записей ГП", default=0)
  updated_links_count = models.PositiveIntegerField(verbose_name="Обновлено связей", default=0)
  error = models.TextField(verbose_name="Ошибка", null=True, blank=True)
  started_at = models.DateTimeField(verbose_name="Начало", auto_now_add=True)
  finished_at = models.DateTimeField(verbose_name="Окончание", null=True, blank=True)

  class Meta:
    ordering = ("-started_at",)
    verbose_name = "Копирование товаров поставщика в ГП"
    verbose_name_plural = "Копирование товаров поставщика в ГП"
