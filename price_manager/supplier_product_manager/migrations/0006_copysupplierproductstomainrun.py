from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('supplier_manager', '0001_initial'),
        ('supplier_product_manager', '0005_alter_supplierfile_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='CopySupplierProductsToMainRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('started', 'Выполняется'), ('success', 'Успешно'), ('error', 'Ошибка')], db_index=True, default='started', max_length=16, verbose_name='Статус')),
                ('filter_params', models.JSONField(blank=True, default=dict, verbose_name='Параметры фильтра')),
                ('processed_count', models.PositiveIntegerField(default=0, verbose_name='Обработано записей')),
                ('created_count', models.PositiveIntegerField(default=0, verbose_name='Создано новых записей ГП')),
                ('updated_links_count', models.PositiveIntegerField(default=0, verbose_name='Обновлено связей')),
                ('error', models.TextField(blank=True, null=True, verbose_name='Ошибка')),
                ('started_at', models.DateTimeField(auto_now_add=True, verbose_name='Начало')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='Окончание')),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='copy_to_main_runs', to='supplier_manager.supplier', verbose_name='Поставщик')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='copy_to_main_runs', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Копирование товаров поставщика в ГП',
                'verbose_name_plural': 'Копирование товаров поставщика в ГП',
                'ordering': ('-started_at',),
            },
        ),
    ]
