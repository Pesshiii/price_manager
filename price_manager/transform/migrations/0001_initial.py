from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='SnapshotField',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(unique=True)),
                ('name', models.CharField(max_length=255, verbose_name='Название')),
                ('value_type', models.CharField(
                    choices=[('number', 'Число'), ('string', 'Строка'), ('boolean', 'Булево')],
                    max_length=16,
                    verbose_name='Тип значения',
                )),
                ('description', models.TextField(blank=True, null=True, verbose_name='Описание')),
            ],
            options={
                'verbose_name': 'Поле снимка',
                'verbose_name_plural': 'Поля снимков',
                'ordering': ['slug'],
            },
        ),
    ]
