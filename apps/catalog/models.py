"""Marketplace Catalog, Dynamic Attributes, Moderation History, Verified Reviews, CMS Banners, Promo."""
import uuid
from django.conf import settings
from django.db import models
from config.utils import normalize_search_text


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    name_ru = models.CharField(max_length=120, blank=True)
    name_en = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=120, unique=True)
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    icon_name = models.CharField(max_length=40, default="grid")
    installment_allowed = models.BooleanField(default=True, help_text="Ko‘chmas mulk kabi taqiqlangan toifalar uchun False (27.1)")
    prohibition_note = models.CharField(max_length=255, blank=True)
    attribute_schema = models.JSONField(default=list, help_text="Dynamic category attributes definition")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "categories"
        ordering = ["sort_order", "name"]


class Brand(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    is_verified = models.BooleanField(default=True)

    class Meta:
        db_table = "brands"
        ordering = ["name"]


class ProductStatus(models.TextChoices):
    DRAFT = "Draft", "Qoralama"
    PENDING_REVIEW = "Pending Review", "Moderatsiyada"
    APPROVED = "Approved", "Tasdiqlangan"
    REJECTED = "Rejected", "Rad etilgan"
    ARCHIVED = "Archived", "Arxiv"


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey("sellers.Store", on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    sku = models.CharField(max_length=80)
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True)
    description = models.TextField()
    specs = models.JSONField(default=dict)
    cash_price = models.PositiveBigIntegerField()
    old_price = models.PositiveBigIntegerField(null=True, blank=True)
    discount_ends_at = models.DateTimeField(null=True, blank=True)
    warranty_months = models.PositiveIntegerField(default=12)
    return_days = models.PositiveIntegerField(default=14)
    delivery_sla_days = models.PositiveIntegerField(default=2)
    installment_eligible = models.BooleanField(default=True)
    resell_risk_level = models.CharField(max_length=16, default="LOW", choices=[("LOW", "Past"), ("MEDIUM", "O‘rta"), ("HIGH", "Yuqori (Qayta sotish xavfi)")])
    status = models.CharField(max_length=24, choices=ProductStatus.choices, default=ProductStatus.DRAFT, db_index=True)
    rejection_reason = models.TextField(blank=True)
    rating = models.FloatField(default=0.0)
    review_count = models.PositiveIntegerField(default=0)
    sales_count = models.PositiveIntegerField(default=0)
    search_index = models.TextField(blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        unique_together = [("store", "sku")]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        brand_name = self.brand.name if self.brand_id else ""
        cat_name = self.category.name if self.category_id else ""
        self.search_index = normalize_search_text(f"{self.title} {brand_name} {cat_name} {self.sku} {self.description}")
        if self.category_id and not self.category.installment_allowed:
            self.installment_eligible = False
        super().save(*args, **kwargs)


class ProductImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image_url = models.CharField(max_length=500)
    alt_text = models.CharField(max_length=180, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "product_images"
        ordering = ["sort_order"]


class ProductVersion(models.Model):
    """Stores pending edits to active products for moderator diff review (Section 5.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField(default=1)
    previous_snapshot = models.JSONField(default=dict)
    proposed_snapshot = models.JSONField(default=dict)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=24, choices=ProductStatus.choices, default=ProductStatus.PENDING_REVIEW)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "product_versions"
        ordering = ["-created_at"]


class ProductModeration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="moderation_logs")
    moderator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    decision = models.CharField(max_length=24, choices=[("Approved", "Tasdiqlandi"), ("Rejected", "Rad etildi"), ("Flagged", "Tekshiruvga olindi")])
    reason_code = models.CharField(max_length=64, blank=True)
    comment = models.TextField(blank=True)
    previous_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "product_moderation"
        ordering = ["-created_at"]


class Review(models.Model):
    """Only verified purchasers may leave a review (Section 29.2 & 31.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField()
    seller_reply = models.TextField(blank=True)
    is_verified_purchase = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews"
        unique_together = [("product", "user")]
        ordering = ["-created_at"]


class Wishlist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlisted_by")
    notify_on_price_drop = models.BooleanField(default=True)
    target_price = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wishlists"
        unique_together = [("user", "product")]


class Banner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=160)
    subtitle = models.CharField(max_length=255)
    badge_text = models.CharField(max_length=60, default="ZARVON")
    cta_label = models.CharField(max_length=60, default="Ko‘rish")
    target_route = models.CharField(max_length=120, default="#catalog")
    theme_variant = models.CharField(max_length=24, default="navy")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "banners"
        ordering = ["sort_order"]


class PromoCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=120)
    discount_pct = models.FloatField(default=0.0)
    discount_fixed = models.PositiveBigIntegerField(default=0)
    min_order_amount = models.PositiveBigIntegerField(default=0)
    max_budget_uzs = models.PositiveBigIntegerField(default=50000000)
    used_budget_uzs = models.PositiveBigIntegerField(default=0)
    per_user_limit = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "promo_codes"
