import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0004_charactype_unicode_slug'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CharacteristicMutationJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(choices=[('retype', 'Retype'), ('rename', 'Rename')], max_length=16)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('running', 'Running'),
                        ('success', 'Success'),
                        ('error', 'Error'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=16,
                )),
                ('stage', models.CharField(blank=True, default='', max_length=64)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('result', models.JSONField(blank=True, null=True)),
                ('error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('char_type', models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name='mutation_jobs',
                    to='product.characteristictype',
                )),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name='char_mutation_jobs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user', '-created_at'], name='product_charmut_user_created_idx')],
            },
        ),
    ]
