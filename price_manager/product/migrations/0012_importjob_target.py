from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0011_nullable_supplierlink_product_and_feedmapping_columns'),
    ]

    operations = [
        migrations.AddField(
            model_name='importjob',
            name='target',
            field=models.CharField(
                choices=[('product', 'Товары'), ('category', 'Категории')],
                default='product',
                max_length=16,
            ),
        ),
    ]
