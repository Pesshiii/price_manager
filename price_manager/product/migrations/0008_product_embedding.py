import pgvector.django.indexes
import pgvector.django.vector
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0007_pgvector_extension'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='embedding',
            field=pgvector.django.vector.VectorField(
                blank=True,
                dimensions=256,
                null=True,
                verbose_name='Эмбеддинг',
            ),
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
        migrations.AddIndex(
            model_name='product',
            index=pgvector.django.indexes.HnswIndex(
                ef_construction=64,
                fields=['embedding'],
                m=16,
                name='product_emb_hnsw',
                opclasses=['vector_cosine_ops'],
            ),
        ),
    ]
