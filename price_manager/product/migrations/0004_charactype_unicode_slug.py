from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0003_importjob_stage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='characteristictype',
            name='name',
            field=models.SlugField(allow_unicode=True, max_length=64, unique=True, verbose_name='Ключ'),
        ),
    ]
