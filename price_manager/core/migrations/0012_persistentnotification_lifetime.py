from datetime import timedelta

from django.db import migrations, models
from django.db.models import F


def expire_existing(apps, schema_editor):
    # Old rows carry no kind, so exports and confirmations cannot be told apart
    # reliably: they keep the 72 hours they were created under.
    PersistentNotification = apps.get_model('core', 'PersistentNotification')
    PersistentNotification.objects.update(
        seen_at=F('created_at'),
        expires_at=F('created_at') + timedelta(hours=72),
    )


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
        migrations.RunPython(expire_existing, migrations.RunPython.noop),
    ]
