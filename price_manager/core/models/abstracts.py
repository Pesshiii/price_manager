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
       )
    slug = models.SlugField(
       unique=True,
       blank=True
    )
    
    class Meta:
        abstract = True
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)   
        super().save(*args, **kwargs)
