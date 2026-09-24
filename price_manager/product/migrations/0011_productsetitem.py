import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0010_product_export'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductSetItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('component_pim_product_id', models.CharField(max_length=64, verbose_name='Id компонента в PIM (Product)')),
                ('component_number', models.CharField(blank=True, default='', max_length=128, verbose_name='Артикул компонента в PIM')),
                ('component_name', models.CharField(blank=True, default='', max_length=512, verbose_name='Название компонента в PIM')),
                ('amount', models.PositiveIntegerField(default=1, verbose_name='Количество')),
                ('sorting', models.IntegerField(default=0, verbose_name='Порядок')),
                ('component', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='in_sets', to='product.product', verbose_name='Компонент')),
                ('set_product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='set_items', to='product.product', verbose_name='Набор')),
            ],
            options={
                'verbose_name': 'Позиция набора',
                'verbose_name_plural': 'Состав наборов',
                'ordering': ['sorting', 'pk'],
                'constraints': [models.UniqueConstraint(fields=('set_product', 'component_pim_product_id'), name='product_setitem_set_component_uniq')],
            },
        ),
    ]
