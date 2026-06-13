from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('supplier_feed', '0011_feedmapping_text_matching'),
    ]

    operations = [
        CreateExtension('pg_trgm'),
        migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS product_name_trgm_idx ON product_product USING GIN(name gin_trgm_ops);",
            reverse_sql="DROP INDEX IF EXISTS product_name_trgm_idx;",
        ),
    ]
