from .base import *
from .api import *
from .project import *
from .celery_settings import *
from .databases import *
from .messages import *
from .storages import *
from .third_party import *

INSTALLED_APPS = INSTALLED_APPS + THIRD_PARTY_INSTALLED_APPS + PROJECT_INSTALLED_APPS
MIDDLEWARE = MIDDLEWARE + THIRD_PARTY_INSTALLED_APPS + PROJECT_INSTALLED_APPS