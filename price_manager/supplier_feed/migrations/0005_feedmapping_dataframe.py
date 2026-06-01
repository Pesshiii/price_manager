import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add required FeedMapping.dataframe FK to Dataframe (pipeline as data source).

    Supersedes ADR-0001 §9. See ADR-0004.
    """

    dependencies = [
        ('dataframe', '0001_initial'),
        ('supplier_feed', '0004_supplier_fk_to_supplier_app'),
    ]

    operations = [
        migrations.AddField(
            model_name='feedmapping',
            name='dataframe',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='feed_mappings',
                to='dataframe.dataframe',
                verbose_name='Pipeline',
            ),
            preserve_default=False,
        ),
    ]
