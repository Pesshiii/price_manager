from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0006_migrate_supplier_categories'),
    ]

    operations = [
        CreateExtension('vector'),
    ]
