import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_alter_cartitem_search_query'),
        ('main_product_manager', '0004_mainproduct_pim_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartitem',
            name='confirmed_product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='confirmed_cart_items', to='main_product_manager.mainproduct', verbose_name='Подтверждённый товар'),
        ),
    ]
