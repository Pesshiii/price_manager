from rest_framework.pagination import PageNumberPagination


class ProductPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class CharacteristicTypePagination(PageNumberPagination):
    """Bound /characteristic-types/ — after EAV-style import the table can hold
    thousands of types; sending the whole list freezes the SPA. Default page
    bumped to 200 so existing UI that listed everything still gets a usable
    page, with explicit opt-out for admin pages via ?page_size=2000."""

    page_size = 200
    page_size_query_param = 'page_size'
    max_page_size = 2000


class ReferenceTablePagination(PageNumberPagination):
    """For Category/Brand reference tables. After EAV imports these can also
    grow into the thousands because the importer auto-creates Category/Brand
    by name. Default 500 covers typical catalogs; opt out with ?page_size."""

    page_size = 500
    page_size_query_param = 'page_size'
    max_page_size = 5000
