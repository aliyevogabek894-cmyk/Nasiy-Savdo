"""Seller Invitations (token hash only), Onboarding Workflow, Store Tenants, Staff & Private Docs."""
import secrets
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from config.utils import encrypt_field, decrypt_field, hash_token, mask_value


class SellerOnboardingStatus(models.TextChoices):
    INVITED = "Invited", "Invited"
    STARTED = "Started", "Started"
    SUBMITTED = "Submitted", "Submitted"
    NEEDS_INFO = "Needs Info", "Needs Info"
    UNDER_REVIEW = "Under Review", "Under Review"
    APPROVED = "Approved", "Approved"
    REJECTED = "Rejected", "Rejected"
    SUSPENDED = "Suspended", "Suspended"
    TERMINATED = "Terminated", "Terminated"


class SellerInvitation(models.Model):
    """Single-use invitation storing ONLY cryptographic hash of the invite token (Section 4.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(max_length=160)
    target_phone = models.CharField(max_length=20, blank=True)
    target_email = models.EmailField(blank=True)
    invited_role = models.CharField(max_length=32, default="SELLER_OWNER")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default=SellerOnboardingStatus.INVITED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="sent_seller_invitations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "seller_invitations"
        ordering = ["-created_at"]

    @classmethod
    def issue_invitation(cls, *, company_name: str, target_phone: str, target_email: str, expires_hours: int, created_by):
        raw_token = secrets.token_urlsafe(32)
        invite = cls.objects.create(
            company_name=company_name,
            target_phone=target_phone,
            target_email=target_email,
            token_hash=hash_token(raw_token),
            expires_at=timezone.now() + timezone.timedelta(hours=expires_hours),
            created_by=created_by,
        )
        return invite, raw_token

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and timezone.now() <= self.expires_at


class SellerApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invitation = models.OneToOneField(SellerInvitation, on_delete=models.SET_NULL, null=True, blank=True, related_name="application")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="seller_applications")
    legal_name = models.CharField(max_length=200)
    public_name = models.CharField(max_length=160)
    entity_type = models.CharField(max_length=32, default="MChJ", choices=[("MChJ", "MChJ"), ("YaTT", "YaTT"), ("AJ", "AJ")])
    stir_number = models.CharField(max_length=24, blank=True)
    representative_name = models.CharField(max_length=160)
    official_phone = models.CharField(max_length=20)
    official_email = models.EmailField(blank=True)
    legal_address = models.CharField(max_length=255)
    return_address = models.CharField(max_length=255)
    bank_details_encrypted = models.TextField(blank=True)
    product_categories = models.JSONField(default=list)
    delivery_regions = models.JSONField(default=list)
    terms_accepted_version = models.CharField(max_length=32, default="2026.3")
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=SellerOnboardingStatus.choices, default=SellerOnboardingStatus.SUBMITTED, db_index=True)
    reason_code = models.CharField(max_length=64, blank=True)
    reviewer_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_seller_apps")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "seller_applications"
        ordering = ["-created_at"]

    def set_bank_details(self, bank_info: str):
        self.bank_details_encrypted = encrypt_field(bank_info)

    def get_masked_bank_details(self) -> str:
        raw = decrypt_field(self.bank_details_encrypted)
        return mask_value(raw, 4, 4) if raw else ""


class Store(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_stores")
    application = models.OneToOneField(SellerApplication, on_delete=models.SET_NULL, null=True, blank=True, related_name="store")
    legal_name = models.CharField(max_length=200)
    public_name = models.CharField(max_length=160, db_index=True)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    logo_text = models.CharField(max_length=4, default="ZV")
    official_phone = models.CharField(max_length=20)
    official_email = models.EmailField(blank=True)
    legal_address = models.CharField(max_length=255)
    return_address = models.CharField(max_length=255)
    working_hours = models.CharField(max_length=80, default="09:00 – 21:00")
    return_policy = models.TextField(default="14 kun ichida asl holatda qaytarish mumkin.")
    delivery_regions = models.JSONField(default=list)
    bank_account_encrypted = models.TextField(blank=True)
    commission_pct = models.FloatField(default=7.5)
    holdback_pct = models.FloatField(default=10.0)
    holdback_days = models.PositiveIntegerField(default=7)
    settlement_days = models.PositiveIntegerField(default=3)
    rating = models.FloatField(default=4.8)
    status = models.CharField(
        max_length=24,
        default="Active",
        choices=[("Active", "Faol"), ("Suspended", "To‘xtatilgan"), ("Terminated", "Tugatilgan")],
    )
    suspension_reason = models.TextField(blank=True)
    is_verified = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stores"
        ordering = ["public_name"]

    def get_masked_bank(self) -> str:
        raw = decrypt_field(self.bank_account_encrypted)
        return mask_value(raw, 4, 4) if raw else "****"


class SellerStaff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="staff_members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seller_staff_roles")
    position_title = models.CharField(max_length=80, default="Katalog va buyurtmalar menejeri")
    allowed_sections = models.JSONField(default=list)  # e.g. ["products", "orders", "inventory"]
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "seller_staff"
        unique_together = [("store", "user")]


class SellerDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(SellerApplication, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=64)
    file_name = models.CharField(max_length=180)
    private_path = models.CharField(max_length=255)
    malware_scan_status = models.CharField(max_length=20, default="CLEAN", choices=[("PENDING", "Tekshirilmoqda"), ("CLEAN", "Xavfsiz"), ("QUARANTINED", "Karantin")])
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "seller_documents"
