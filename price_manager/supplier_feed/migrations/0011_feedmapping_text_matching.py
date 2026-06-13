from django.db import migrations, models


def backfill_name_column(apps, schema_editor):
    FeedMapping = apps.get_model('supplier_feed', 'FeedMapping')
    to_update = []
    for fm in FeedMapping.objects.filter(name_column=''):
        fm.name_column = fm.supplier_sku_column
        to_update.append(fm)
    if to_update:
        FeedMapping.objects.bulk_update(to_update, ['name_column'])


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_feed', '0010_feedcolumnmapping_supplier_feed_column_mapping_price_requires_type'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='feedmapping',
            name='identity_columns',
        ),
        migrations.RenameField(
            model_name='feedmapping',
            old_name='product_name_column',
            new_name='name_column',
        ),
        migrations.RunPython(backfill_name_column, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='feedmapping',
            name='name_column',
            field=models.CharField(max_length=128, verbose_name='Колонка названия товара'),
        ),
        migrations.AddField(
            model_name='feedmapping',
            name='low_match_threshold',
            field=models.FloatField(default=0.5, verbose_name='Нижний порог совпадения'),
        ),
    ]
