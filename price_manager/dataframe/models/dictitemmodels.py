from django.db import models

class DictItem(models.Model):
    link = models.ForeignKey('Link',
                            on_delete=models.CASCADE,
                            verbose_name='Столбец',
                            related_name='dicts',
                            blank=True,
                            null=True)
    key = models.CharField(verbose_name='Если')
    value = models.CharField(verbose_name='То')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['link', 'key', 'value'], name='linkdict')]