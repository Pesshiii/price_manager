from django.db import migrations, models


def copy_category_to_categories(apps, schema_editor):
    MainProduct = apps.get_model('main_product_manager', 'MainProduct')
    for product in MainProduct.objects.exclude(category__isnull=True).iterator():
        product.categories.add(product.category_id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0007_category_search_vector'),
        ('main_product_manager', '0004_mainproduct_pim_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='mainproduct',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='mainproducts', to='supplier_manager.category', verbose_name='Категории'),
        ),
        migrations.RunPython(copy_category_to_categories, noop),
        migrations.RemoveField(
            model_name='mainproduct',
            name='category',
        ),
        migrations.AlterField(
            model_name='mainproduct',
            name='pim_id',
            field=models.CharField(blank=True, null=True, verbose_name='Id для системы Pim'),
        ),
    ]
