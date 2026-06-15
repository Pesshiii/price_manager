from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0012_remove_embedding'),
    ]

    operations = [
        migrations.AddField(
            model_name='importjob',
            name='default_status',
            field=models.CharField(blank=True, default='', max_length=16, verbose_name='Статус по умолчанию'),
        ),
    ]
