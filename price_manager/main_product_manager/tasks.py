from django.db import transaction
from django.db.models import Count
from django.db.models import  Q

from celery import shared_task

from .models import MainProduct, MainProductDuplicate, DUPLICATE_LOOKUPS
from .functions import apply_lookup
