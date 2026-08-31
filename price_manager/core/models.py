from django.db import models
from django.db.models import TextChoices
from main_product_manager.models import MainProduct
# Обработка заявок

class CartItem(models.Model):
    user = models.ForeignKey(
        'auth.User',
        verbose_name='Пользователь',
        on_delete=models.CASCADE,
        related_name='cart_items')
    search_query = models.CharField(verbose_name='Поисковый запрос', null=True, blank=True)
    products = models.ManyToManyField(
        MainProduct,
        verbose_name='Товар',
        related_name='cart_items')
    confirmed_product = models.ForeignKey(
        MainProduct,
        verbose_name='Подтверждённый товар',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_cart_items')
    quantity = models.PositiveIntegerField(verbose_name='Количество', default=1)

    # Какая из цен MainProduct считается ценой позиции — решается здесь и только здесь.
    PRICE_FIELD = 'basic_price'

    @property
    def confirmed_price(self):
        """Цена подтверждённого товара или None."""
        if not self.confirmed_product:
            return None
        return getattr(self.confirmed_product, self.PRICE_FIELD, None)

    @property
    def line_total(self):
        """Сумма по позиции: цена × количество."""
        price = self.confirmed_price
        if price is None:
            return None
        return price * self.quantity

class ShoppingTab(models.Model):
    user = models.ForeignKey(
        'auth.User',
        verbose_name='Пользователь',
        on_delete=models.CASCADE,
        related_name='shopping_tabs')
    name = models.CharField(verbose_name='Название',
                          null=False)
    file = models.FileField(verbose_name='Файл',
                          upload_to='shopping_tabs/',
                          null=True,
                          blank=True)
    items = models.ManyToManyField(CartItem,
                                    verbose_name='Элементы корзины',
                                    related_name='shopping_tabs')
    open = models.BooleanField(verbose_name='Открыта',
                             default=True)
    class Meta:
        verbose_name = 'Заявка'
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='user_name_constraint')]

class ShoppingTabExport(models.Model):
    tab = models.ForeignKey(
        ShoppingTab,
        verbose_name='Заявка',
        on_delete=models.CASCADE,
        related_name='exports')
    user = models.ForeignKey(
        'auth.User',
        verbose_name='Пользователь',
        on_delete=models.CASCADE,
        related_name='shopping_tab_exports')
    file = models.FileField(
        verbose_name='Файл',
        upload_to='shopping_tab_exports/',
        null=True,
        blank=True)
    rows_count = models.PositiveIntegerField(verbose_name='Строк', default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Экспорт заявки'
        verbose_name_plural = 'Экспорты заявок'

    def __str__(self):
        return f'{self.tab.name} — {self.created_at:%d.%m.%Y %H:%M}'


class LevelChoices(TextChoices):
    INFO = 'info', 'Инфо'
    SUCCESS = 'success', 'Успех'
    WARNING = 'warning', 'Предупреждение'
    DANGER = 'danger', 'Ошибка'

class PersistentNotification(models.Model):

    user = models.ForeignKey(
        'auth.User',
        verbose_name='Пользователь',
        on_delete=models.CASCADE,
        related_name='persistent_notifications',
    )
    level = models.CharField(
        max_length=16, 
        choices=LevelChoices.choices, 
        default=LevelChoices.INFO, 
        verbose_name='Уровень')
    message = models.TextField(verbose_name='Сообщение')
    # Необязательная кнопка-действие: например, ссылка на скачивание экспорта.
    link = models.CharField(verbose_name='Ссылка', max_length=500, null=True, blank=True)
    link_text = models.CharField(verbose_name='Текст ссылки', max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Постоянное уведомление'
        verbose_name_plural = 'Постоянные уведомления'

    def __str__(self):
        return f"{self.user}: {self.message[:40]}"

class StatusChoices(TextChoices):
    SUCCESS = 'success', 'Успешно'
    ERROR = 'error', 'Ошибка'
    SKIPPED = 'skipped', 'Пропущено (lock)'

class TaskRunHistory(models.Model):
    task_name = models.CharField(max_length=255, verbose_name='Имя задачи', db_index=True)
    status = models.CharField(max_length=16, choices=StatusChoices.choices, verbose_name='Статус')
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
