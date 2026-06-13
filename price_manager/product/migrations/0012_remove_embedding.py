from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0011_nullable_supplierlink_product_and_feedmapping_columns'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='product',
            name='product_emb_hnsw',
        ),
        migrations.RemoveField(
            model_name='product',
            name='embedding',
        ),
        migrations.RemoveField(
            model_name='product',
            name='embedding_text_hash',
        ),
    ]
