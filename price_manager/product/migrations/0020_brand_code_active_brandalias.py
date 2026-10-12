"""Синонимы брендов и зеркало всего списка брендов PIM.

Первый шаг перехода на «товар = (бренд, артикул)»: бренд из прайса поставщика
сопоставляется с брендом PIM через BrandAlias. Сразу заводятся синонимы
«игнорировать» — написания, которые означают отсутствие бренда, в том числе
страны: страна-«бренд» склеила бы по артикулу товары разных производителей.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

IGNORED_NAMES = ['Без бренда', 'Нет бренда', 'Noname', 'Russia', 'Россия']


def seed_ignored(apps, schema_editor):
    from product.models import brand_key

    BrandAlias = apps.get_model('product', 'BrandAlias')
    for name in IGNORED_NAMES:
        BrandAlias.objects.get_or_create(name_key=brand_key(name), defaults={'name': name, 'brand': None})


def unseed_ignored(apps, schema_editor):
    from product.models import brand_key

    BrandAlias = apps.get_model('product', 'BrandAlias')
    BrandAlias.objects.filter(
        name_key__in=[brand_key(name) for name in IGNORED_NAMES], brand__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0019_productphoto'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='brand',
            name='code',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Код в PIM'),
        ),
        migrations.AddField(
            model_name='brand',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='Действует в PIM'),
        ),
        migrations.CreateModel(
            name='BrandAlias',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_key', models.CharField(unique=True, verbose_name='Ключ написания')),
                ('name', models.CharField(verbose_name='Написание')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Добавлен')),
                ('brand', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                            related_name='aliases', to='product.brand', verbose_name='Бренд')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name='+', to=settings.AUTH_USER_MODEL,
                                                 verbose_name='Кто добавил')),
            ],
            options={
                'verbose_name': 'Синоним бренда',
                'verbose_name_plural': 'Синонимы брендов',
                'ordering': ['name'],
            },
        ),
        migrations.RunPython(seed_ignored, unseed_ignored),
    ]
