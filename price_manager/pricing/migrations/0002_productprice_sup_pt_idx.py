# Generated manually - add composite index on ProductPrice(supplier, price_type)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pricing', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='productprice',
            index=models.Index(fields=['supplier', 'price_type'], name='pricing_pp_sup_pt_idx'),
        ),
    ]
