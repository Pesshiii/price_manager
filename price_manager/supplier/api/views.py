from __future__ import annotations

from rest_framework import viewsets

from ..models import Supplier
from .serializers import SupplierSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    """CRUD для поставщиков.

    list   GET    /api/suppliers/
    create POST   /api/suppliers/
    retrieve GET  /api/suppliers/<id>/
    update  PUT   /api/suppliers/<id>/
    partial_update PATCH /api/suppliers/<id>/
    destroy DELETE /api/suppliers/<id>/
    """

    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
