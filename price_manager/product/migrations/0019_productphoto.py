import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0018_drop_api_stack'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductPhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pim_file_id', models.CharField(db_index=True, max_length=64, verbose_name='Id файла в PIM')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('is_main', models.BooleanField(default=False, verbose_name='Главное')),
                ('public_url', models.URLField(blank=True, default='', max_length=500, verbose_name='Публичная ссылка')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='product.product', verbose_name='Товар')),
            ],
            options={
                'verbose_name': 'Фото товара',
                'verbose_name_plural': 'Фото товаров',
                'ordering': ['position', 'pk'],
                'constraints': [models.UniqueConstraint(fields=('product', 'pim_file_id'), name='product_photo_file_uniq')],
            },
        ),
    ]
