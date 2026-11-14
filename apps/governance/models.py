"""Immutable Audit Logs, Security Events, Versioned BHM & Compliance Rules, Notifications."""
import uuid
from django.conf import settings
from django.db import models
from config.middleware import get_client_ip, get_correlation_id


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actor_role = models.CharField(max_length=32, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=64, db_index=True)
    object_id = models.CharField(max_length=64, blank=True)
    reason = models.TextField(blank=True)
    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]

    @classmethod
    def record(cls, *, actor=None, action: str, object_type: str, object_id: str = "", reason: str = "", before=None, after=None):
        return cls.objects.create(
            actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
            actor_role=getattr(actor, "role", "SYSTEM") if actor else "SYSTEM",
            action=action,
            object_type=object_type,
            object_id=str(object_id or ""),
            reason=reason,
            before_data=before or {},
            after_data=after or {},
            correlation_id=get_correlation_id(),
            ip_address=get_client_ip(),
        )


class SecurityEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=16, choices=[("LOW", "Past"), ("MEDIUM", "O‘rta"), ("HIGH", "Yuqori"), ("CRITICAL", "Kritik")])
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.CharField(max_length=64, blank=True)
    description = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_security_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "security_events"
        ordering = ["-created_at"]


class BhmValue(models.Model):
    """Bazaviy Hisoblash Miqdori — stored in DB & versioned (Section 27.1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    amount_uzs = models.PositiveBigIntegerField(default=440000)
    effective_from = models.DateField()
    is_active = models.BooleanField(default=True, db_index=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bhm_values"
        ordering = ["-effective_from", "-created_at"]

    @classmethod
    def get_current_amount(cls) -> int:
        active = cls.objects.filter(is_active=True).first()
        return active.amount_uzs if active else 440000


class ComplianceRuleVersion(models.Model):
    """Statutory rules for installment service compliance guard (Section 27.1, 28.3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version_code = models.CharField(max_length=32, unique=True)
    max_months = models.PositiveIntegerField(default=12)
    max_bhm_multiplier = models.PositiveIntegerField(default=250)
    max_annual_extra_pct = models.FloatField(default=50.0)
    early_repayment_fee_pct = models.FloatField(default=0.0)
    legal_basis_note = models.TextField()
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "compliance_rule_versions"
        ordering = ["-created_at"]

    @classmethod
    def get_active(cls):
        rule = cls.objects.filter(is_active=True).first()
        if not rule:
            rule = cls.objects.create(
                version_code="UZ-2027-V1",
                max_months=12,
                max_bhm_multiplier=250,
                max_annual_extra_pct=50.0,
                early_repayment_fee_pct=0.0,
                legal_basis_note="2027-yil 1-yanvardan kuchga kiradigan muddatli to‘lov qoidalari (12 oy, 250 BHM, yiliga 50% chegara, 0% erta to‘lov jarimasi).",
                is_active=True,
            )
        return rule


class NotificationEvent(models.Model):
    """Notification log separating OTP/transactional from marketing; never includes passport/PINFL."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=16, choices=[("SMS", "SMS"), ("EMAIL", "Email"), ("PUSH", "Push"), ("TELEGRAM", "Telegram")])
    category = models.CharField(max_length=20, choices=[("OTP", "OTP"), ("TRANSACTIONAL", "Tranzaksion"), ("MARKETING", "Marketing")])
    status = models.CharField(
        max_length=16,
        default="delivered",
        choices=[("queued", "Navbatda"), ("sent", "Yuborildi"), ("delivered", "Yetkazildi"), ("failed", "Xato"), ("retry", "Qayta urinish")],
    )
    title = models.CharField(max_length=160)
    body_masked = models.TextField()
    correlation_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_events"
        ordering = ["-created_at"]


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference")
    sms_transactional = models.BooleanField(default=True)
    telegram_alerts = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    marketing_opt_in = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_preferences"


class RetentionDeletionRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="privacy_requests")
    request_type = models.CharField(max_length=20, choices=[("EXPORT", "Ma'lumot eksporti"), ("CORRECTION", "Tuzatish"), ("DELETION", "O'chirish")])
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="PENDING", choices=[("PENDING", "Kutilmoqda"), ("COMPLETED", "Bajarildi"), ("REJECTED", "Rad etildi")])
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_privacy_requests")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "retention_jobs"
        ordering = ["-created_at"]
