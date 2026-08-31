import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0007_category_search_vector'),
        ('main_product_manager', '0005_mainproduct_categories_m2m'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mainproduct',
            name='supplier',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='main_products', to='supplier_manager.supplier', verbose_name='Поставщик'),
        ),
    ]
