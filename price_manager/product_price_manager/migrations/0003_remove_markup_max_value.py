from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0002_uniquepricemanager'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pricemanager',
            name='markup',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5, validators=[MinValueValidator(-100)], verbose_name='Накрутка'),
        ),
        migrations.AlterField(
            model_name='specialprice',
            name='markup',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5, validators=[MinValueValidator(-100)], verbose_name='Накрутка'),
        ),
    ]
