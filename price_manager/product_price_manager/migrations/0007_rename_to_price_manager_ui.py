"""UI names: PriceManager is «Менеджер цен», PriceTag is «Наценка»."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product_price_manager', '0006_remove_pricemanager_categories'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='pricemanager',
            options={'ordering': ['dest', 'source'], 'verbose_name': 'Менеджер цен',
                     'verbose_name_plural': 'Менеджеры цен'},
        ),
        migrations.AlterField(
            model_name='pricetag',
            name='p_manager',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='pricetags', to='product_price_manager.pricemanager',
                                    verbose_name='Менеджер цен'),
        ),
    ]
