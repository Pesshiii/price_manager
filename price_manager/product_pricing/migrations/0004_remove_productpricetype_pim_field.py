from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('product_pricing', '0003_productpricerule_products'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='productpricetype',
            name='pim_field',
        ),
    ]
