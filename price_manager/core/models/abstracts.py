import uuid

from django.db import models
from django.utils.text import slugify




class TimeStampedModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now =True)
    class Meta:
        abstract = True

class SlugModel(models.Model):
    name = models.CharField(
       max_length=200,
       unique=True,
       verbose_name="Название",
       blank=True,
       )
    slug = models.SlugField(
       unique=True,
       blank=True,
       allow_unicode=True,
    )
    
    class Meta:
        abstract = True
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True) or str(uuid.uuid4())[:8]
        super().save(*args, **kwargs)
