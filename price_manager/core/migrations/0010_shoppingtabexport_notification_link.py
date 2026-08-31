import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0009_cartitem_confirmed_product'),
    ]

    operations = [
        migrations.AddField(
            model_name='persistentnotification',
            name='link',
            field=models.CharField(blank=True, max_length=500, null=True, verbose_name='Ссылка'),
        ),
        migrations.AddField(
            model_name='persistentnotification',
            name='link_text',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='Текст ссылки'),
        ),
        migrations.CreateModel(
            name='ShoppingTabExport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(blank=True, null=True, upload_to='shopping_tab_exports/', verbose_name='Файл')),
                ('rows_count', models.PositiveIntegerField(default=0, verbose_name='Строк')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tab', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exports', to='core.shoppingtab', verbose_name='Заявка')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shopping_tab_exports', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Экспорт заявки',
                'verbose_name_plural': 'Экспорты заявок',
                'ordering': ('-created_at',),
            },
        ),
    ]
