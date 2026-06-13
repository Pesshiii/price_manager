from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0007_pgvector_extension'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE product_product ADD COLUMN IF NOT EXISTS embedding vector(256);",
            reverse_sql="ALTER TABLE product_product DROP COLUMN IF EXISTS embedding;",
            state_operations=[
                migrations.AddField(
                    model_name='product',
                    name='embedding',
                    field=models.TextField(
                        blank=True,
                        null=True,
                        verbose_name='Эмбеддинг',
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name='product',
            name='embedding_text_hash',
            field=models.CharField(
                blank=True,
                default='',
                max_length=64,
                verbose_name='Хэш эмбед-текста',
            ),
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS product_emb_hnsw ON product_product USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);",
            reverse_sql="DROP INDEX IF EXISTS product_emb_hnsw;",
            state_operations=[
                migrations.AddIndex(
                    model_name='product',
                    index=models.Index(fields=['embedding'], name='product_emb_hnsw'),
                ),
            ],
        ),
    ]
