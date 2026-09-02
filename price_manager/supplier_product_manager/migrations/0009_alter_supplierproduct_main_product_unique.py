from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_product_manager', '0008_decouple_and_unique_main_product'),
    ]

    operations = [
        migrations.AlterField(
            model_name='supplierproduct',
            name='main_product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='supplierproducts',
                to='main_product_manager.mainproduct',
                unique=True,
                verbose_name='sku',
            ),
        ),
    ]
