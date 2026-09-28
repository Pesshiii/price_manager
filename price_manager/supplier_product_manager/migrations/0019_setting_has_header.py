from django.db import migrations, models


class Migration(migrations.Migration):
    """index_row → has_header. Every setting gets has_header=True: the header
    row is now found by functions.find_header_row, which also covers the
    settings whose index_row pointed below a block of supplier details."""

    dependencies = [
        ('supplier_product_manager', '0018_importrun_missing_columns_unparsed'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='has_header',
            field=models.BooleanField(default=True, verbose_name='С заголовками'),
        ),
        migrations.RemoveField(
            model_name='setting',
            name='index_row',
        ),
    ]
