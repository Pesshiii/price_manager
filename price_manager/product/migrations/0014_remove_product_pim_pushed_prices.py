from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0013_product_supplier_prices'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='product',
            name='pim_pushed_prices',
        ),
    ]
