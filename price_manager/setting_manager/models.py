from django.db import models

LINKS = {
    '': 'Не включать',
    'article': 'Артикул поставщика',
    'name': 'Название',
    'category': 'Категория',
    'discounts': 'Группа скидок',
    'manufacturer': 'Производитель',
    'stock': 'Остаток',
    'supplier_price': 'Цена поставщика в валюте поставщика',
    'rrp': 'РРЦ в валюте поставщика',
}


class Setting(models.Model):
    name = models.CharField(verbose_name='Название')
    supplier = models.ForeignKey(
        'supplier_manager.Supplier',
        on_delete=models.CASCADE,
        verbose_name='Поставщик',
    )
    sheet_name = models.CharField(verbose_name='Название листа')
    priced_only = models.BooleanField(verbose_name='Не включать поля без цены', default=True)
    update_main = models.BooleanField(verbose_name='Обновлять главный прайс', default=True)
    differ_by_name = models.BooleanField(verbose_name='Различать по имени', default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['name', 'supplier'], name='name_supplier_constraint')]
        verbose_name = 'Настройка'
        verbose_name_plural = 'Настройки'

    def __str__(self):
        return self.name


class Link(models.Model):
    setting = models.ForeignKey(Setting, on_delete=models.CASCADE)
    initial = models.CharField(null=True)
    key = models.CharField(choices=LINKS)
    value = models.CharField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['setting', 'key'], name='product-field-constraint')]
        verbose_name = 'Связка'
        verbose_name_plural = 'Связки'


class Dict(models.Model):
    link = models.ForeignKey(
        Link,
        on_delete=models.CASCADE,
        verbose_name='Столбец',
        blank=True,
        null=True,
    )
    key = models.CharField(verbose_name='Если')
    value = models.CharField(verbose_name='То')

    class Meta:
        verbose_name = 'Словарь'
        verbose_name_plural = 'Словари'

