from django.db import migrations


class Migration(migrations.Migration):
    """Merge the two conflicting 0009 leaf migrations."""

    dependencies = [
        ('supplier_feed', '0009_feedcolumnmapping'),
        ('supplier_feed', '0009_remove_feedmarkupset_feed_mapping_feedcolumnmapping_and_more'),
        ('supplier_feed', '0010_feedcolumnmapping_supplier_feed_column_mapping_price_requires_type'),
    ]

    operations = []
