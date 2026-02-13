from django.conf import settings
from django.db import models
from django.urls import reverse


class Article(models.Model):
    title = models.CharField('Заголовок', max_length=255)
    content = models.TextField('Текст статьи')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='Автор',
        on_delete=models.PROTECT,
        related_name='articles',
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Статья'
        verbose_name_plural = 'Статьи'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('blogapp:article-detail', kwargs={'pk': self.pk})
