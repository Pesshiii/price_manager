from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pricemanager',
            name='markup',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=20,
                validators=[django.core.validators.MinValueValidator(-100)],
                verbose_name='Накрутка',
            ),
        ),
        migrations.AlterField(
            model_name='pricetag',
            name='markup',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=20,
                validators=[django.core.validators.MinValueValidator(-100)],
                verbose_name='Накрутка',
            ),
        ),
    ]
