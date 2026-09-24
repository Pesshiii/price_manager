import re

from django.db import migrations, models

IMPORT_RUN_IN_LINK = re.compile(r'[?&]import_run=(\d+)')


def classify_existing(apps, schema_editor):
    # Old rows carry no kind; each manual one is recognisable by the link its
    # single call site wrote. Everything else stays regular and unseen, so its
    # countdown starts at the next panel open like any new notification.
    PersistentNotification = apps.get_model('core', 'PersistentNotification')
    PersistentNotification.objects.filter(link_text='Скачать файл').update(kind='export')
    PersistentNotification.objects.filter(link__startswith='/releases/').update(kind='release')
    for notification in PersistentNotification.objects.filter(link_text='Проверить', link__contains='import_run='):
        match = IMPORT_RUN_IN_LINK.search(notification.link)
        if match:
            # Ones no longer pending go with the next cleanup_supplier_files_task.
            notification.kind = 'confirmation'
            notification.ref = f'import_run:{match.group(1)}'
            notification.save(update_fields=['kind', 'ref'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_bitrix24account'),
    ]

    operations = [
        migrations.AddField(
            model_name='persistentnotification',
            name='kind',
            field=models.CharField(choices=[('regular', 'Обычное'), ('export', 'Выгрузка'), ('confirmation', 'Подтверждение'), ('release', 'Обновление')], default='regular', max_length=16, verbose_name='Вид'),
        ),
        migrations.AddField(
            model_name='persistentnotification',
            name='ref',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64, verbose_name='Объект'),
        ),
        migrations.AddField(
            model_name='persistentnotification',
            name='seen_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Впервые показано'),
        ),
        migrations.AddField(
            model_name='persistentnotification',
            name='expires_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Удалить после'),
        ),
        migrations.RunPython(classify_existing, migrations.RunPython.noop),
    ]
