from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dataframe', '0008_alter_dataframe_file'),
    ]

    operations = [
        migrations.AlterField(
            model_name='link',
            name='value',
            field=models.CharField(
                blank=True,
                null=True,
                verbose_name='Столбец значения',
            ),
        ),
    ]
