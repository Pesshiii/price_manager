from django.db import models
from main_product_manager.models import MainProduct
# Обработка заявок

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