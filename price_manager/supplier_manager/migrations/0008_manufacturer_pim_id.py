from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0007_category_search_vector'),
    ]

    operations = [
        migrations.AddField(
            model_name='manufacturer',
            name='pim_id',
            field=models.CharField(blank=True, null=True, unique=True, verbose_name='Id для системы Pim'),
        ),
    ]
