"""Inventory Warehouses, Stock Levels, Low-Stock Alerts & Movements APIs."""
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission
from apps.governance.models import AuditLog
from apps.inventory.models import StockLevel, StockMovement


class InventoryStockView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN", "DELIVERY_MANAGER", "AUDITOR", "SELLER_OWNER", "SELLER_STAFF"}

    def get(self, request):
        qs = StockLevel.objects.select_related("product__store", "warehouse").prefetch_related("movements")
        if request.user.role in {"SELLER_OWNER", "SELLER_STAFF"}:
            qs = qs.filter(product__store_id__in=request.user.get_accessible_store_ids())
        return Response(
            {
                "results": [
                    {
                        "stock_id": str(s.id),
                        "product_id": str(s.product_id),
                        "sku": s.product.sku,
                        "product_title": s.product.title,
                        "store_name": s.product.store.public_name,
                        "warehouse_name": s.warehouse.name if s.warehouse else "Asosiy ombor",
                        "quantity": s.quantity,
                        "reserved": s.reserved,
                        "available": s.available,
                        "min_threshold": s.min_threshold,
                        "is_low_stock": s.is_low_stock,
                        "recent_movements": [
                            {"type": m.movement_type, "delta": m.delta, "note": m.note, "created_at": m.created_at}
                            for m in s.movements.all()[:5]
                        ],
                    }
                    for s in qs[:60]
                ]
            }
        )

    @transaction.atomic
    def post(self, request):
        stock_id = request.data.get("stock_id")
        delta = int(request.data.get("delta") or 0)
        note = (request.data.get("note") or "Ombor inventarizatsiyasi").strip()
        stock = StockLevel.objects.select_for_update().select_related("product__store").filter(id=stock_id).first()
        if not stock:
            return Response({"detail": "Ombor yozuvi topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.role in {"SELLER_OWNER", "SELLER_STAFF"} and stock.product.store_id not in request.user.get_accessible_store_ids():
            return Response({"detail": "Boshqa sotuvchi omborini o‘zgartirish taqiqlangan."}, status=status.HTTP_403_FORBIDDEN)

        new_qty = stock.quantity + delta
        if new_qty < stock.reserved:
            return Response({"detail": f"Qoldiq band qilingan ({stock.reserved} dona) miqdordan kam bo‘lishi mumkin emas."}, status=status.HTTP_400_BAD_REQUEST)
        stock.quantity = new_qty
        stock.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            stock=stock,
            movement_type="INBOUND" if delta > 0 else "ADJUST",
            delta=delta,
            note=note,
            created_by=request.user,
        )
        AuditLog.record(actor=request.user, action="STOCK_ADJUSTED", object_type="StockLevel", object_id=stock.id, reason=note, after={"quantity": new_qty})
        return Response({"ok": True, "quantity": stock.quantity, "available": stock.available})
