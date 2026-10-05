from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('supplier_manager', '0015_supplier_is_unsupplied'),
        # 0009 ищет служебного поставщика по старому имени поля — переименование
        # строго после неё.
        ('product_price_manager', '0009_unsupplied_supplier'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='supplier',
            name='supplier_single_unsupplied',
        ),
        migrations.RenameField(
            model_name='supplier',
            old_name='is_unsupplied',
            new_name='is_own_stock',
        ),
        migrations.AlterField(
            model_name='supplier',
            name='is_own_stock',
            field=models.BooleanField(default=False, editable=False, verbose_name='Свой склад'),
        ),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(condition=models.Q(('is_own_stock', True)), fields=('is_own_stock',), name='supplier_single_own_stock'),
        ),
    ]
