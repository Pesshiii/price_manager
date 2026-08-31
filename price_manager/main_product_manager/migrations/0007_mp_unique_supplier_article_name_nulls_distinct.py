from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main_product_manager', '0006_alter_mainproduct_supplier'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='mainproduct',
            name='mp_unique_supplier_article_name',
        ),
        migrations.AddConstraint(
            model_name='mainproduct',
            constraint=models.UniqueConstraint(
                fields=('supplier', 'article', 'name'),
                name='mp_unique_supplier_article_name',
                nulls_distinct=False,
            ),
        ),
    ]
