from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('developers', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='feedback',
            name='rendered_url',
            field=models.CharField(blank=True, max_length=500, verbose_name='Страница загрузки'),
        ),
    ]
