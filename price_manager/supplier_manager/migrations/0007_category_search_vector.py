import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0006_alter_category_parent'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='search_vector',
            field=django.contrib.postgres.search.SearchVectorField(editable=False, null=True, verbose_name='Вектор поиска'),
        ),
        migrations.AddIndex(
            model_name='category',
            index=django.contrib.postgres.indexes.GinIndex(fields=['search_vector'], name='category_search_vector_gin'),
        ),
    ]
