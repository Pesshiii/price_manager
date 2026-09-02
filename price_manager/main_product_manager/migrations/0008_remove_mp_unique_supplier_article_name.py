from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0007_mp_unique_supplier_article_name_nulls_distinct'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='mainproduct',
            name='mp_unique_supplier_article_name',
        ),
    ]
