"""Cart, Master/Sub-Order Splitting, Price Snapshots, Delivery OTP, Returns & Refunds."""
import uuid
from django.conf import settings
from django.db import models
from config.utils import generate_otp_code, hash_token


class DeliveryPoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    region = models.CharField(max_length=80)
    address = models.CharField(max_length=255)
    working_hours = models.CharField(max_length=80, default="09:00 – 21:00")
    latitude = models.FloatField(default=41.3111)
    longitude = models.FloatField(default=69.2797)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "delivery_points"


class Cart(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carts"


class CartItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cart_items"
        unique_together = [("cart", "product")]


class OrderStatus(models.TextChoices):
    PENDING = "Pending", "Kutilmoqda"
    AWAITING_FINANCE = "Awaiting Finance", "Moliyalashtirish kutilmoqda"
    CONFIRMED = "Confirmed", "Tasdiqlangan"
    PROCESSING = "Processing", "Tayyorlanmoqda"
    SHIPPED = "Shipped", "Jo‘natilgan"
    DELIVERED = "Delivered", "Topshirilgan"
    CANCELLED = "Cancelled", "Bekor qilingan"
    RETURN_REQUESTED = "Return Requested", "Qaytarish so‘ralgan"
    RETURNED_REFUNDED = "Returned/Refunded", "Qaytarilgan"


class Order(models.Model):
    """Master Customer Order; splits into SellerOrder per vendor (Section 7.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=32, unique=True, db_index=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    payment_channel = models.CharField(
        max_length=24,
        choices=[("DIRECT_PAY", "Naqd / Karta / PSP"), ("ZARVON_NASIYA", "ZARVON Nasiya"), ("BANK_GATEWAY", "Bank Krediti (Gateway)")],
    )
    payment_method_label = models.CharField(max_length=64, default="Uzcard / Humo")
    delivery_type = models.CharField(max_length=24, choices=[("COURIER", "Kuryer"), ("PICKUP", "Yig‘ish punkti")], default="COURIER")
    delivery_address = models.CharField(max_length=255, blank=True)
    delivery_point = models.ForeignKey(DeliveryPoint, on_delete=models.SET_NULL, null=True, blank=True)
    promo_code_used = models.CharField(max_length=40, blank=True)
    subtotal_amount = models.PositiveBigIntegerField()
    discount_amount = models.PositiveBigIntegerField(default=0)
    total_amount = models.PositiveBigIntegerField()
    status = models.CharField(max_length=24, choices=OrderStatus.choices, default=OrderStatus.PENDING)
    idempotency_key = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders"
        ordering = ["-created_at"]


class SellerOrder(models.Model):
    """Per-seller sub-order with independent fulfillment & delivery OTP confirmation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    master_order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="seller_orders")
    store = models.ForeignKey("sellers.Store", on_delete=models.PROTECT, related_name="seller_orders")
    sub_order_number = models.CharField(max_length=40, unique=True)
    subtotal_amount = models.PositiveBigIntegerField()
    commission_amount = models.PositiveBigIntegerField(default=0)
    holdback_amount = models.PositiveBigIntegerField(default=0)
    net_seller_payout = models.PositiveBigIntegerField(default=0)
    payout_status = models.CharField(max_length=24, default="HELD", choices=[("HELD", "Ushlab turilgan"), ("SCHEDULED", "Rejalashtirilgan"), ("PAID", "To‘langan"), ("ADJUSTED", "Tuzatilgan")])
    status = models.CharField(max_length=24, choices=OrderStatus.choices, default=OrderStatus.PENDING)
    delivery_otp_hash = models.CharField(max_length=64, blank=True)
    delivery_otp_demo = models.CharField(max_length=8, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "seller_orders"
        ordering = ["-created_at"]

    def issue_delivery_otp(self) -> str:
        code = generate_otp_code(6)
        self.delivery_otp_hash = hash_token(code)
        self.delivery_otp_demo = code  # Shown only to customer in demo/sandbox UI for courier handover
        self.save(update_fields=["delivery_otp_hash", "delivery_otp_demo"])
        return code


class OrderItem(models.Model):
    """Price snapshot at purchase time — subsequent catalog price updates never alter past orders (Section 7.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_order = models.ForeignKey(SellerOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    product_title_snapshot = models.CharField(max_length=220)
    sku_snapshot = models.CharField(max_length=80)
    unit_price_snapshot = models.PositiveBigIntegerField()
    quantity = models.PositiveIntegerField()
    line_total = models.PositiveBigIntegerField()

    class Meta:
        db_table = "order_items"


class Shipment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_order = models.OneToOneField(SellerOrder, on_delete=models.CASCADE, related_name="shipment")
    courier_name = models.CharField(max_length=100, default="ZARVON Express")
    tracking_number = models.CharField(max_length=64, unique=True)
    estimated_delivery = models.DateField(null=True, blank=True)
    handover_proof = models.CharField(max_length=255, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "shipments"


class ReturnRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_order = models.ForeignKey(SellerOrder, on_delete=models.CASCADE, related_name="return_requests")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    return_scope = models.CharField(max_length=16, choices=[("FULL", "To‘liq qaytarish"), ("PARTIAL", "Qisman qaytarish")], default="FULL")
    items_payload = models.JSONField(default=list)
    refund_amount = models.PositiveBigIntegerField(default=0)
    reason = models.TextField()
    photo_evidence_note = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=24,
        default="PENDING",
        choices=[("PENDING", "Tekshirilmoqda"), ("APPROVED", "Tasdiqlandi"), ("REJECTED", "Rad etildi"), ("REFUNDED", "Qaytarildi")],
    )
    decision_note = models.TextField(blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_returns")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "returns"
        ordering = ["-created_at"]


class RefundRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_request = models.OneToOneField(ReturnRequest, on_delete=models.CASCADE, related_name="refund_record")
    amount = models.PositiveBigIntegerField()
    channel = models.CharField(max_length=32)
    status = models.CharField(max_length=24, default="COMPLETED")
    reconciliation_ref = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refunds"
