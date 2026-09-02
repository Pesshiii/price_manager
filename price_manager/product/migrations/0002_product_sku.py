from django.db import migrations, models
import django.contrib.postgres.indexes


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='sku',
            field=models.CharField(blank=True, max_length=128, null=True, verbose_name='Артикул'),
        ),
        migrations.AddField(
            model_name='product',
            name='description',
            field=models.TextField(blank=True, null=True, verbose_name='Описание'),
        ),
        migrations.AddField(
            model_name='product',
            name='status',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='Статус'),
        ),
        migrations.AddField(
            model_name='product',
            name='characteristics',
            field=models.JSONField(blank=True, default=dict, verbose_name='Характеристики'),
        ),
        migrations.AddField(
            model_name='product',
            name='image_urls',
            field=models.JSONField(blank=True, default=list, verbose_name='Изображения'),
        ),
        migrations.AddField(
            model_name='product',
            name='brand',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.PROTECT, related_name='products', to='product.brand', verbose_name='Бренд'),
        ),
        migrations.AddField(
            model_name='product',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.PROTECT, related_name='products', to='product.category', verbose_name='Категория'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=django.contrib.postgres.indexes.GinIndex(fields=['characteristics'], name='product_chars_gin_idx'),
        ),
    ]
