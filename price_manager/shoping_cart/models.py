from django.db import models


class AlternateProduct(models.Model):
    name = models.CharField(verbose_name='Название')
    main_product = models.ForeignKey(
        'main_price.MainProduct',
        verbose_name='Главный продукт',
        related_name='alternate_products',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'main_product'], name='name_main_product_constraint'),
        ]
        verbose_name = 'Альтернативный товар'
        verbose_name_plural = 'Альтернативные товары'

    def __str__(self):
        return self.name


class ShopingTab(models.Model):
    user = models.ForeignKey(
        'auth.User',
        verbose_name='Пользователь',
        on_delete=models.CASCADE,
        related_name='shoping_tabs',
    )
    name = models.CharField(verbose_name='Название')
    products = models.ManyToManyField(
        AlternateProduct,
        verbose_name='Товары',
        related_name='shoping_tabs',
    )
    open = models.BooleanField(verbose_name='Открыта', default=True)

    class Meta:
        verbose_name = 'Заявка'
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='user_name_constraint')]

    def __str__(self):
        return f'{self.user} — {self.name}'
