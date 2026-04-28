from django.db import models

# Create your models here.

class Product(models.Model):
    class Meta:
        abstract = True