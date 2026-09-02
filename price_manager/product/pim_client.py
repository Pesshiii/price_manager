from django.conf import settings

from pim_api import SiteAPI

site = SiteAPI(token=settings.PIM_TOKEN, host=settings.PIM_HOST, debug=settings.DEBUG)
