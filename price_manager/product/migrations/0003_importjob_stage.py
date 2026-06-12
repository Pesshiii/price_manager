from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0002_importjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='importjob',
            name='stage',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
