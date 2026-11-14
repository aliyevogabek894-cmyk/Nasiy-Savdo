"""Warehouses, Stock Levels, Stock Movements, and Oversell-Blocking Reservations."""
import uuid
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class Warehouse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("sellers.Store", on_delete=models.CASCADE, related_name="warehouses")
    name = models.CharField(max_length=120)
    region = models.CharField(max_length=100, default="Toshkent")
    address = models.CharField(max_length=255)
    is_default = models.BooleanField(default=True)

    class Meta:
        db_table = "warehouses"


class StockLevel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.OneToOneField("catalog.Product", on_delete=models.CASCADE, related_name="stock")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_levels")
    quantity = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    min_threshold = models.PositiveIntegerField(default=3)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_levels"

    @property
    def available(self) -> int:
        return max(0, self.quantity - self.reserved)

    @property
    def is_low_stock(self) -> bool:
        return self.available <= self.min_threshold


class StockMovement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock = models.ForeignKey(StockLevel, on_delete=models.CASCADE, related_name="movements")
    movement_type = models.CharField(
        max_length=24,
        choices=[("INBOUND", "Kirim"), ("OUTBOUND", "Chiqim"), ("RESERVE", "Band qilish"), ("RELEASE", "Bo‘shatish"), ("ADJUST", "Inventarizatsiya")],
    )
    delta = models.IntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_movements"
        ordering = ["-created_at"]


class Reservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock = models.ForeignKey(StockLevel, on_delete=models.CASCADE, related_name="reservations")
    order_ref = models.CharField(max_length=64, db_index=True)
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default="ACTIVE", choices=[("ACTIVE", "Faol"), ("CONSUMED", "Yakunlandi"), ("RELEASED", "Bo‘shatildi"), ("EXPIRED", "Muddati tugadi")])
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reservations"

    @classmethod
    @transaction.atomic
    def reserve_for_order(cls, product_id, qty: int, order_ref: str, actor=None):
        """Atomic row-level lock prevents overselling under concurrent checkouts (Section 23.1)."""
        stock = StockLevel.objects.select_for_update().get(product_id=product_id)
        if stock.available < qty:
            raise ValueError(f"Omborda yetarli qoldiq yo‘q (mavjud: {stock.available} dona).")
        stock.reserved += qty
        stock.save(update_fields=["reserved", "updated_at"])
        res = cls.objects.create(
            stock=stock,
            order_ref=order_ref,
            quantity=qty,
            expires_at=timezone.now() + timezone.timedelta(minutes=30),
        )
        StockMovement.objects.create(
            stock=stock,
            movement_type="RESERVE",
            delta=-qty,
            note=f"Buyurtma uchun band qilindi: {order_ref}",
            created_by=actor,
        )
        return res
