import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_feed', '0001_initial'),
        ('supplier_manager', '0001_initial'),
        ('product', '0010_charmutationjob_progress'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupplierFeed',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Черновик'),
                        ('processing', 'Обрабатывается'),
                        ('matched', 'Сматчено'),
                        ('partial', 'Частично'),
                        ('done', 'Завершено'),
                        ('error', 'Ошибка'),
                    ],
                    db_index=True,
                    default='draft',
                    max_length=16,
                    verbose_name='Статус',
                )),
                ('session_ids', models.JSONField(default=list, verbose_name='ID сессий файлов')),
                ('error', models.TextField(blank=True, verbose_name='Ошибка')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('feed_mapping', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='supplier_feeds',
                    to='supplier_feed.feedmapping',
                    verbose_name='Конфигурация',
                )),
                ('supplier', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='supplier_feeds',
                    to='supplier_manager.supplier',
                    verbose_name='Поставщик',
                )),
            ],
            options={
                'verbose_name': 'Сессия выгрузки',
                'verbose_name_plural': 'Сессии выгрузок',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SupplierFeedEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('supplier_sku', models.CharField(db_index=True, max_length=128, verbose_name='Артикул поставщика')),
                ('data', models.JSONField(default=dict, verbose_name='Данные строки')),
                ('match_candidates', models.JSONField(default=list, verbose_name='Кандидаты на матчинг')),
                ('skipped', models.BooleanField(default=False, verbose_name='Пропущено')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('feed', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='entries',
                    to='supplier_feed.supplierfeed',
                    verbose_name='Сессия',
                )),
                ('product', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='product.product',
                    verbose_name='Товар',
                )),
            ],
            options={
                'verbose_name': 'Строка выгрузки',
                'verbose_name_plural': 'Строки выгрузок',
            },
        ),
        migrations.AddIndex(
            model_name='supplierfeedentry',
            index=models.Index(fields=['feed', 'product'], name='sf_entry_feed_product_idx'),
        ),
        migrations.AddIndex(
            model_name='supplierfeedentry',
            index=models.Index(fields=['feed', 'supplier_sku'], name='sf_entry_feed_sku_idx'),
        ),
        migrations.CreateModel(
            name='SupplierLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('supplier_sku', models.CharField(max_length=128, verbose_name='Артикул поставщика')),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='product.product',
                    verbose_name='Товар',
                )),
                ('supplier', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='supplier_manager.supplier',
                    verbose_name='Поставщик',
                )),
            ],
            options={
                'verbose_name': 'Связь поставщик — товар',
                'verbose_name_plural': 'Связи поставщик — товар',
            },
        ),
        migrations.AlterUniqueTogether(
            name='supplierlink',
            unique_together={('supplier', 'supplier_sku')},
        ),
    ]
