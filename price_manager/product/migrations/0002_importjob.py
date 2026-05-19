import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ImportJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('kind', models.CharField(choices=[('preview', 'Preview'), ('commit', 'Commit')], max_length=16)),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('running', 'Running'), ('success', 'Success'), ('error', 'Error')],
                    db_index=True,
                    default='pending',
                    max_length=16,
                )),
                ('session_id', models.CharField(max_length=64)),
                ('instructions', models.JSONField(blank=True, default=dict)),
                ('mapping', models.JSONField(blank=True, default=dict)),
                ('row_limit', models.PositiveIntegerField(default=200)),
                ('result', models.JSONField(blank=True, null=True)),
                ('error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name='product_import_jobs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user', '-created_at'], name='product_imp_user_id_created_idx')],
            },
        ),
    ]
