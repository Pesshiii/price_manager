import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Switch FeedMapping, SupplierFeed and SupplierLink supplier FKs
    from supplier_manager.Supplier to the new supplier.Supplier model.
    """

    dependencies = [
        ('supplier', '0001_initial'),
        ('supplier_feed', '0003_fix_entry_index_names'),
    ]

    operations = [
        migrations.AlterField(
            model_name='feedmapping',
            name='supplier',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='feed_mappings',
                to='supplier.supplier',
                verbose_name='Поставщик',
            ),
        ),
        migrations.AlterField(
            model_name='supplierfeed',
            name='supplier',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='supplier_feeds',
                to='supplier.supplier',
                verbose_name='Поставщик',
            ),
        ),
        migrations.AlterField(
            model_name='supplierlink',
            name='supplier',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to='supplier.supplier',
                verbose_name='Поставщик',
            ),
        ),
    ]
