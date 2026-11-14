"""Identity, RBAC, MFA, OTP, Session Management, and Maker-Checker models."""
import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from config.utils import encrypt_field, decrypt_field, hash_identifier, mask_value


class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    MARKETPLACE_ADMIN = "MARKETPLACE_ADMIN", "Marketplace Admin"
    FINANCE_OFFICER = "FINANCE_OFFICER", "Finance Officer"
    RISK_MANAGER = "RISK_MANAGER", "Risk Manager"
    COLLECTIONS_AGENT = "COLLECTIONS_AGENT", "Collections Agent"
    FRAUD_ANALYST = "FRAUD_ANALYST", "Fraud Analyst"
    CONTENT_MANAGER = "CONTENT_MANAGER", "Content Manager"
    DELIVERY_MANAGER = "DELIVERY_MANAGER", "Delivery Manager"
    FINANCE_OPERATIONS = "FINANCE_OPERATIONS", "Finance Operations"
    SUPPORT_AGENT = "SUPPORT_AGENT", "Support Agent"
    AUDITOR = "AUDITOR", "Auditor"
    SELLER_OWNER = "SELLER_OWNER", "Seller Owner"
    SELLER_STAFF = "SELLER_STAFF", "Seller Staff"
    CUSTOMER = "CUSTOMER", "Customer"


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Telefon raqami majburiy")
        phone = phone.strip()
        user = self.model(phone=phone, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("mfa_enabled", True)
        return self.create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True, db_index=True)
    full_name = models.CharField(max_length=160)
    role = models.CharField(max_length=32, choices=UserRole.choices, default=UserRole.CUSTOMER, db_index=True)
    preferred_language = models.CharField(max_length=5, default="uz")
    theme_preference = models.CharField(max_length=10, default="light")
    mfa_enabled = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    kyc_status = models.CharField(
        max_length=24,
        default="UNVERIFIED",
        choices=[
            ("UNVERIFIED", "Tasdiqlanmagan"),
            ("PENDING", "Tekshirilmoqda"),
            ("VERIFIED", "Tasdiqlangan"),
            ("REJECTED", "Rad etilgan"),
        ],
    )
    # Sensitive identity fields stored encrypted + keyed HMAC hash for duplicate prevention
    pinfl_hash = models.CharField(max_length=64, blank=True, db_index=True)
    pinfl_encrypted = models.TextField(blank=True)
    inn_hash = models.CharField(max_length=64, blank=True, db_index=True)
    inn_encrypted = models.TextField(blank=True)
    passport_encrypted = models.TextField(blank=True)
    birth_year = models.PositiveIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        ordering = ["-created_at"]

    def set_identity_fields(self, pinfl: str = "", passport: str = "", inn: str = ""):
        if pinfl:
            clean_pinfl = pinfl.strip()
            self.pinfl_hash = hash_identifier(clean_pinfl)
            self.pinfl_encrypted = encrypt_field(clean_pinfl)
        if inn:
            clean_inn = inn.strip()
            self.inn_hash = hash_identifier(clean_inn)
            self.inn_encrypted = encrypt_field(clean_inn)
        if passport:
            self.passport_encrypted = encrypt_field(passport.strip().upper())

    def get_masked_pinfl(self) -> str:
        raw = decrypt_field(self.pinfl_encrypted)
        return mask_value(raw, 4, 2) if raw else ""

    def get_masked_inn(self) -> str:
        raw = decrypt_field(self.inn_encrypted)
        return mask_value(raw, 3, 2) if raw else ""

    def get_masked_passport(self) -> str:
        raw = decrypt_field(self.passport_encrypted)
        return mask_value(raw, 2, 2) if raw else ""

    def get_accessible_store_ids(self):
        from apps.sellers.models import Store, SellerStaff
        owned = list(Store.objects.filter(owner=self).values_list("id", flat=True))
        staff = list(SellerStaff.objects.filter(user=self, is_active=True).values_list("store_id", flat=True))
        return list(set(owned + staff))

    def __str__(self):
        return f"{self.full_name} ({self.phone}) [{self.role}]"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    region = models.CharField(max_length=100, default="Toshkent shahri")
    address = models.CharField(max_length=255, blank=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    telegram_chat_id = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "profiles"


class UserSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_sessions")
    device_name = models.CharField(max_length=120, default="Web Browser")
    ip_address = models.CharField(max_length=64, default="127.0.0.1")
    is_revoked = models.BooleanField(default=False)
    last_active = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_sessions"
        ordering = ["-last_active"]


class MfaDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfa_devices")
    device_type = models.CharField(max_length=20, choices=[("OTP_SMS", "SMS OTP"), ("TOTP", "Authenticator App"), ("HARDWARE", "Hardware Key")])
    label = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mfa_devices"


class OtpChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target = models.CharField(max_length=120, db_index=True)
    purpose = models.CharField(max_length=32, default="LOGIN")
    code_hash = models.CharField(max_length=64)
    demo_hint = models.CharField(max_length=12, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "otp_challenges"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at


class MakerCheckerRequest(models.Model):
    """Two-person approval for high-risk actions (role escalation, policy/BHM, bank details, restructuring)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action_type = models.CharField(max_length=64)
    target_model = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict)
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        default="PENDING",
        choices=[("PENDING", "Kutilmoqda"), ("APPROVED", "Tasdiqlandi"), ("REJECTED", "Rad etildi")],
    )
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="maker_requests")
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="checker_approvals")
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "maker_checker_requests"
        ordering = ["-created_at"]
