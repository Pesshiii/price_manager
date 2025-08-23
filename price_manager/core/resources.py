from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import *


class MainProductResource(resources.ModelResource):
    supplier_name = fields.Field(
        column_name='supplier',
        attribute='supplier',
        widget=ForeignKeyWidget(Supplier, field='name')
    )
    class Meta:
        model = MainProduct
        fields = [f'''{field}{'_name'*(field=='supplier')}''' for field in MP_FIELDS if field not in ['updated_at']]
        export_order = fields
        import_id_fields = ['sku']