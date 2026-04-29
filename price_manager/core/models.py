from django.db import models
from main_product_manager.models import MainProduct
# Обработка заявок


class TimeStampedModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now =True)
    class Meta:
        abstract = True

class AlternateProduct(models.Model):
  name = models.CharField(verbose_name='Название',
                          null=False)
  # filter = models.JSONField(verbose_name='Фильтр',
  #                           null=True)
  main_product = models.ForeignKey(MainProduct, 
                                    verbose_name='Главный продукт',
                                    related_name='alternate_products',
                                    on_delete=models.SET_NULL,
                                    null=True,
                                    blank=True)
  class Meta:
    constraints = [models.UniqueConstraint(fields=['name', 'main_product'], name='name_main_product_constraint')]

class ShopingTab(models.Model):
  user = models.ForeignKey('auth.User',
                           verbose_name='Пользователь',
                           on_delete=models.CASCADE,
                           related_name='shoping_tabs')
  name = models.CharField(verbose_name='Название',
                          null=False)
  products = models.ManyToManyField(AlternateProduct,
                                    verbose_name='Товары',
                                    related_name='shoping_tabs')
  open = models.BooleanField(verbose_name='Открыта',
                             default=True)
  class Meta:
    verbose_name = 'Заявка'
    constraints = [models.UniqueConstraint(fields=['user', 'name'], name='user_name_constraint')]

class PersistentNotification(models.Model):
  LEVEL_CHOICES = [
    ('info', 'Инфо'),
    ('success', 'Успех'),
    ('warning', 'Предупреждение'),
    ('danger', 'Ошибка'),
  ]

  user = models.ForeignKey(
    'auth.User',
    verbose_name='Пользователь',
    on_delete=models.CASCADE,
    related_name='persistent_notifications',
  )
  level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default='info')
  message = models.TextField(verbose_name='Сообщение')
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    ordering = ('-created_at',)
    verbose_name = 'Постоянное уведомление'
    verbose_name_plural = 'Постоянные уведомления'

  def __str__(self):
    return f"{self.user}: {self.message[:40]}"


class TaskRunHistory(models.Model):
  STATUS_CHOICES = [
    ('success', 'Успешно'),
    ('error', 'Ошибка'),
    ('skipped', 'Пропущено (lock)'),
  ]

  task_name = models.CharField(max_length=255, verbose_name='Имя задачи', db_index=True)
  status = models.CharField(max_length=16, choices=STATUS_CHOICES, verbose_name='Статус')
  started_at = models.DateTimeField(verbose_name='Начало выполнения')
  finished_at = models.DateTimeField(verbose_name='Окончание выполнения')
  duration_ms = models.PositiveIntegerField(verbose_name='Длительность, мс')
  updated_count = models.IntegerField(default=0, verbose_name='Обновлено записей')
  details = models.JSONField(default=dict, blank=True, verbose_name='Детали')
  error = models.TextField(null=True, blank=True, verbose_name='Ошибка')
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    ordering = ('-started_at',)
    verbose_name = 'История запуска задачи'
    verbose_name_plural = 'История запусков задач'

  def __str__(self):
    return f"{self.task_name} [{self.status}]"
