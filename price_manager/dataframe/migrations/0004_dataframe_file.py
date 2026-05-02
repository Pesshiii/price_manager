from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dataframe', '0003_remove_dataframe_cols_remove_dataframe_conf_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataframe',
            name='file',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='dataframes',
                to='dataframe.filemodel',
                verbose_name='Файл',
                default=1,
            ),
            preserve_default=False,
        ),
    ]
