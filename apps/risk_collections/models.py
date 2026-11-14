"""Risk Scoring (versioned + explainable + appealable), Anti-Fraud, Collections DPD, Support."""
import uuid
from django.conf import settings
from django.db import models


class RiskAssessment(models.Model):
    """Explainable, versioned risk scoring — AI alone never issues final unappealable rejections (Section 9)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_assessments")
    model_version = models.CharField(max_length=32, default="risk-score-v2.1-uz")
    score = models.PositiveIntegerField(default=680)
    dti_ratio_pct = models.FloatField(default=22.0)
    decision = models.CharField(max_length=24, choices=[("APPROVE", "Tasdiqlash"), ("MANUAL_REVIEW", "Inson ko‘rigi"), ("DECLINE", "Rad etish")])
    reason_codes = models.JSONField(default=list)
    recommended_tier = models.CharField(max_length=16, default="Start")
    human_reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_risks")
    appeal_status = models.CharField(max_length=24, default="NONE", choices=[("NONE", "Yo‘q"), ("APPEALED", "Apellyatsiya berildi"), ("OVERTURNED", "Qayta ko‘rilib tasdiqlandi"), ("UPHELD", "O‘z kuchida")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "risk_assessments"
        ordering = ["-created_at"]


class DeviceFingerprint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    fingerprint_hash = models.CharField(max_length=64, db_index=True)
    device_label = models.CharField(max_length=120)
    last_ip = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "device_fingerprints"


class FraudSignal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    signal_type = models.CharField(
        max_length=40,
        choices=[
            ("MULTI_ACCOUNT_PINFL", "Bir PINFL bilan ko‘p akkaunt"),
            ("HIGH_RESELL_RISK", "Qayta sotish xavfi yuqori tovar"),
            ("SELLER_BUYER_COLLUSION", "Sotuvchi-xaridor til biriktirish shubhasi"),
            ("SMS_ABUSE", "OTP / SMS suiiste’moli"),
            ("ACCOUNT_TAKEOVER", "Shubhali kirish / SIM almashishi"),
        ],
    )
    severity = models.CharField(max_length=16, choices=[("LOW", "Past"), ("MEDIUM", "O‘rta"), ("HIGH", "Yuqori")])
    summary = models.TextField()
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fraud_signals"
        ordering = ["-created_at"]


class FraudCase(models.Model):
    """Fraud flag routes to manual review — never automatic guilt (Section 9)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signal = models.ForeignKey(FraudSignal, on_delete=models.CASCADE, related_name="cases")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=24, default="OPEN", choices=[("OPEN", "Ochiq"), ("UNDER_REVIEW", "Tekshirilmoqda"), ("CLEARED", "Toza"), ("CONFIRMED", "Tasdiqlangan xavf")])
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fraud_cases"
        ordering = ["-created_at"]


class CollectionCase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.OneToOneField("finance.InstallmentContract", on_delete=models.CASCADE, related_name="collection_case")
    assigned_agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_collections")
    dpd_days = models.PositiveIntegerField(default=0)
    overdue_amount_uzs = models.PositiveBigIntegerField(default=0)
    stage = models.CharField(
        max_length=24,
        default="PRE_REMINDER",
        choices=[
            ("PRE_REMINDER", "Oldindan eslatma"),
            ("SOFT", "Soft (1–7 kun)"),
            ("MIDDLE", "Middle (8–30 kun)"),
            ("HARD", "Hard (31+ kun)"),
            ("ASSIGNED", "Ruxsatli tashkilotga o‘tkazilgan"),
            ("RESOLVED", "Hal etilgan"),
        ],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "collection_cases"
        ordering = ["-dpd_days"]


class CollectionAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(CollectionCase, on_delete=models.CASCADE, related_name="actions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    channel = models.CharField(max_length=24, choices=[("PUSH", "Push"), ("SMS", "SMS"), ("TELEGRAM", "Telegram"), ("CALL_WORK_HOURS", "Ish vaqtida qo‘ng‘iroq"), ("NOTICE", "Rasmiy ogohlantirish")])
    note = models.TextField()
    respectful_conduct_confirmed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "collection_actions"
        ordering = ["-created_at"]


class RestructuringCase(models.Model):
    """Restructuring requires Collections preparation + second authorized Checker approval (28.5)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey("finance.InstallmentContract", on_delete=models.CASCADE, related_name="restructuring_cases")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_restructurings")
    reason = models.TextField()
    proposed_new_months = models.PositiveIntegerField()  # Must stay <= 12
    status = models.CharField(max_length=24, default="PENDING_CHECKER", choices=[("PENDING_CHECKER", "Ikkinchi tasdiq kutilmoqda"), ("APPROVED", "Tasdiqlandi"), ("REJECTED", "Rad etildi")])
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_restructurings")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "restructuring_cases"
        ordering = ["-created_at"]


class ReceivableAssignment(models.Model):
    """Strict 27.1 rule: receivables may ONLY be assigned to licensed Operator, MFO, or Bank (never arbitrary collectors/individuals)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey("finance.InstallmentContract", on_delete=models.PROTECT)
    assignee_name = models.CharField(max_length=160)
    assignee_license_type = models.CharField(max_length=24, choices=[("OPERATOR", "Nasiya operatori"), ("MFO", "MFO"), ("BANK", "Bank")])
    registry_number = models.CharField(max_length=64)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "receivable_assignments"


class SupportTicket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket_number = models.CharField(max_length=32, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets")
    category = models.CharField(
        max_length=32,
        choices=[
            ("GENERAL", "Umumiy savol"),
            ("COMPLAINT", "Shikoyat"),
            ("RISK_APPEAL", "Skoring / Limit apellyatsiyasi"),
            ("RETURN_DISPUTE", "Qaytarish nizosi"),
            ("SELLER_SUPPORT", "Sotuvchi yordami"),
        ],
    )
    subject = models.CharField(max_length=180)
    messages = models.JSONField(default=list)
    status = models.CharField(max_length=24, default="OPEN", choices=[("OPEN", "Ochiq"), ("IN_PROGRESS", "Ko‘rib chiqilmoqda"), ("RESOLVED", "Hal etildi"), ("CLOSED", "Yopildi")])
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets")
    sla_hours = models.PositiveIntegerField(default=24)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "support_tickets"
        ordering = ["-created_at"]
