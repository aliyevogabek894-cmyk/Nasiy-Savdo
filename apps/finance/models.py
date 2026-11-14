"""Installment Plans, Contracts, Schedules, Early Repayments, Limits, Consents, Multi-Bank & Reconciliation."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from config.utils import compute_monthly_installment
from apps.governance.models import BhmValue, ComplianceRuleVersion


class ConsentPurpose(models.TextChoices):
    IDENTITY = "IDENTITY", "Shaxsni tekshirish (MyID / OneID)"
    CREDIT_BUREAU = "CREDIT_BUREAU", "Kredit hisobotini so‘rash"
    BANK_TRANSFER = "BANK_TRANSFER", "Hamkor banklarga ma’lumot uzatish"
    AUTO_DEBIT = "AUTO_DEBIT", "Kartadan avtomatik yechish"
    MARKETING = "MARKETING", "Marketing va aksiyalar"


class CustomerConsent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=32, choices=ConsentPurpose.choices)
    version = models.CharField(max_length=24, default="2026.3")
    is_granted = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "consent_records"
        ordering = ["-granted_at"]


class IdentityCheck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identity_checks")
    provider = models.CharField(max_length=40, default="MyID Sandbox")
    liveness_passed = models.BooleanField(default=False)
    status = models.CharField(max_length=24, default="PENDING", choices=[("PENDING", "Kutilmoqda"), ("VERIFIED", "Tasdiqlangan"), ("FAILED", "Rad etildi")])
    correlation_id = models.CharField(max_length=64, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity_checks"


class CustomerLimit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="installment_limit")
    tier = models.CharField(max_length=16, default="Start", choices=[("Start", "Start"), ("Plus", "Plus"), ("Max", "Max")])
    total_limit_uzs = models.PositiveBigIntegerField(default=5000000)
    used_limit_uzs = models.PositiveBigIntegerField(default=0)
    is_frozen = models.BooleanField(default=False)
    freeze_reason = models.CharField(max_length=255, blank=True)
    is_demo_limit = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customer_limits"

    @property
    def available_limit_uzs(self) -> int:
        if self.is_frozen:
            return 0
        return max(0, self.total_limit_uzs - self.used_limit_uzs)


class LimitEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_limit = models.ForeignKey(CustomerLimit, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=32, choices=[("INITIAL", "Boshlang‘ich"), ("INCREASE", "Oshirildi"), ("DECREASE", "Kamaytirildi"), ("FREEZE", "Muzlatildi"), ("UNFREEZE", "Ochildi"), ("UTILIZE", "Sarflandi"), ("RESTORE", "Tiklandi")])
    amount_delta = models.BigIntegerField()
    reason = models.CharField(max_length=255)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "limit_events"
        ordering = ["-created_at"]


class InstallmentPlan(models.Model):
    """Configurable 3/6/9/12-month installment plans guarded by ComplianceRuleVersion."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80)
    months = models.PositiveIntegerField()
    annual_markup_pct = models.FloatField(default=24.0)
    commission_pct = models.FloatField(default=2.0)
    late_fee_daily_pct = models.FloatField(default=0.1)
    min_amount_uzs = models.PositiveBigIntegerField(default=300000)
    is_active = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=True)
    compliance_version = models.ForeignKey(ComplianceRuleVersion, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        db_table = "installment_plans"
        ordering = ["months"]

    def clean(self):
        rule = ComplianceRuleVersion.get_active()
        if self.months < 1 or self.months > rule.max_months:
            raise ValidationError(f"Muddat {rule.max_months} oydan oshmasligi shart (Compliance Guard: 27.1).")
        sample = compute_monthly_installment(10_000_000, self.months, self.annual_markup_pct, self.commission_pct)
        if sample["annualized_extra_pct"] > rule.max_annual_extra_pct:
            raise ValidationError(
                f"Yillik qo‘shimcha xarajat ({sample['annualized_extra_pct']}%) ruxsat etilgan {rule.max_annual_extra_pct}% chegarasidan oshdi (Compliance Guard)."
            )

    def save(self, *args, **kwargs):
        if not self.compliance_version_id:
            self.compliance_version = ComplianceRuleVersion.get_active()
        self.full_clean()
        super().save(*args, **kwargs)


class ContractStatus(models.TextChoices):
    DRAFT = "Draft", "Draft"
    SIGNED = "Signed", "Signed"
    ACTIVE = "Active", "Active"
    OVERDUE = "Overdue", "Overdue"
    RESTRUCTURED = "Restructured", "Restructured"
    PREPAID = "Prepaid", "Prepaid"
    CLOSED = "Closed", "Closed"
    CANCELLED = "Cancelled", "Cancelled"
    ASSIGNED = "Assigned", "Assigned"
    WRITTEN_OFF = "WrittenOff", "WrittenOff"


class InstallmentContract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract_number = models.CharField(max_length=40, unique=True, db_index=True)
    order = models.OneToOneField("commerce.Order", on_delete=models.PROTECT, related_name="installment_contract")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="installment_contracts")
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.PROTECT)
    provider_type = models.CharField(max_length=24, choices=[("OWN_NASIYA", "ZARVON Nasiya (Sandbox)"), ("PARTNER_BANK", "Hamkor Bank (Sandbox)")], default="OWN_NASIYA")
    provider_name = models.CharField(max_length=80, default="ZARVON Nasiya Operator (DEMO)")
    principal_amount = models.PositiveBigIntegerField()
    down_payment = models.PositiveBigIntegerField(default=0)
    markup_amount = models.PositiveBigIntegerField(default=0)
    commission_amount = models.PositiveBigIntegerField(default=0)
    total_payable = models.PositiveBigIntegerField()
    remaining_balance = models.PositiveBigIntegerField()
    months = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=ContractStatus.choices, default=ContractStatus.SIGNED, db_index=True)
    signed_method = models.CharField(max_length=16, choices=[("OTP", "SMS OTP"), ("E_IMZO", "E-IMZO")], default="OTP")
    signed_at = models.DateTimeField(null=True, blank=True)
    starts_after_delivery = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=True)
    compliance_rule_code = models.CharField(max_length=32, default="UZ-2027-V1")
    bhm_snapshot_uzs = models.PositiveBigIntegerField(default=440000)
    summary_terms = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "installment_contracts"
        ordering = ["-created_at"]


class InstallmentScheduleItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(InstallmentContract, on_delete=models.CASCADE, related_name="schedule_items")
    installment_no = models.PositiveIntegerField()
    due_date = models.DateField()
    principal_part = models.PositiveBigIntegerField()
    markup_part = models.PositiveBigIntegerField()
    amount_due = models.PositiveBigIntegerField()
    amount_paid = models.PositiveBigIntegerField(default=0)
    penalty_amount = models.PositiveBigIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        default="UPCOMING",
        choices=[("UPCOMING", "Kutilmoqda"), ("PAID", "To‘langan"), ("PARTIAL", "Qisman"), ("OVERDUE", "Kechikkan"), ("WAIVED", "Bekor qilingan")],
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "installment_schedule_items"
        ordering = ["installment_no"]


class RepaymentEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(InstallmentContract, on_delete=models.CASCADE, related_name="repayment_events")
    amount = models.PositiveBigIntegerField()
    payment_method = models.CharField(max_length=32, default="Payme")
    is_early_repayment = models.BooleanField(default=False)
    early_fee = models.PositiveBigIntegerField(default=0)  # Always 0 per Section 27.1!
    idempotency_key = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "repayment_events"
        ordering = ["-created_at"]


class EarlyRepayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(InstallmentContract, on_delete=models.CASCADE, related_name="early_repayments")
    amount = models.PositiveBigIntegerField()
    fee_charged = models.PositiveBigIntegerField(default=0)
    balance_before = models.PositiveBigIntegerField()
    balance_after = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "early_repayments"
        ordering = ["-created_at"]


class BankPartner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=32, unique=True)
    environment = models.CharField(max_length=16, choices=[("SANDBOX", "Sandbox"), ("PRODUCTION", "Production")], default="SANDBOX")
    adapter_status = models.CharField(max_length=16, choices=[("ONLINE", "Ishlayapti"), ("DEGRADED", "Sekinlashgan"), ("TIMEOUT", "Javob bermayapti")], default="ONLINE")
    uptime_pct = models.FloatField(default=99.6)
    avg_latency_ms = models.PositiveIntegerField(default=420)
    base_annual_rate_pct = models.FloatField(default=28.0)
    max_months = models.PositiveIntegerField(default=12)
    webhook_secret_hash = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "bank_partners"


class CreditApplication(models.Model):
    """Multi-Bank Finance Gateway application (Section 8) — strictly uses Consent Gate."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_applications")
    order = models.ForeignKey("commerce.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_applications")
    requested_amount = models.PositiveBigIntegerField()
    requested_months = models.PositiveIntegerField(default=12)
    status = models.CharField(
        max_length=32,
        default="Submitted",
        choices=[
            ("Draft", "Draft"),
            ("Consent Pending", "Consent Pending"),
            ("Submitted", "Submitted"),
            ("Identity Check", "Identity Check"),
            ("Document Review", "Document Review"),
            ("Income/Debt Review", "Income/Debt Review"),
            ("Bank Submitted", "Bank Submitted"),
            ("Bank Pending", "Bank Pending"),
            ("More Info Required", "More Info Required"),
            ("Offer Available", "Offer Available"),
            ("Customer Selected", "Customer Selected"),
            ("Bank Approved", "Bank Approved"),
            ("Bank Declined", "Bank Declined"),
            ("Contract Signed", "Contract Signed"),
            ("Expired", "Expired"),
        ],
    )
    correlation_id = models.CharField(max_length=64, db_index=True)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "credit_applications"
        ordering = ["-created_at"]


class BankApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit_application = models.ForeignKey(CreditApplication, on_delete=models.CASCADE, related_name="bank_submissions")
    bank = models.ForeignKey(BankPartner, on_delete=models.PROTECT)
    correlation_id = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=32, default="Bank Pending")
    error_message = models.CharField(max_length=255, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bank_applications"


class BankOffer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bank_application = models.OneToOneField(BankApplication, on_delete=models.CASCADE, related_name="offer")
    bank = models.ForeignKey(BankPartner, on_delete=models.PROTECT)
    principal_amount = models.PositiveBigIntegerField()
    down_payment = models.PositiveBigIntegerField(default=0)
    months = models.PositiveIntegerField()
    annual_rate_pct = models.FloatField()
    total_cost_of_credit_pct = models.FloatField()
    mandatory_commission = models.PositiveBigIntegerField(default=0)
    monthly_payment = models.PositiveBigIntegerField()
    total_payable = models.PositiveBigIntegerField()
    insurance_optional = models.BooleanField(default=True)
    expires_at = models.DateTimeField()
    is_selected = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=True)

    class Meta:
        db_table = "bank_offers"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at


class WebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=64)
    event_id = models.CharField(max_length=80, unique=True)
    signature_valid = models.BooleanField(default=True)
    payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-received_at"]


class PaymentRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_intent_id = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=32, choices=[("Payme", "Payme"), ("Click", "Click"), ("Uzum Bank", "Uzum Bank"), ("Paynet", "Paynet"), ("Uzcard/Humo", "Uzcard/Humo")])
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    order = models.ForeignKey("commerce.Order", on_delete=models.SET_NULL, null=True, blank=True)
    contract = models.ForeignKey(InstallmentContract, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=8, default="UZS")
    status = models.CharField(max_length=24, default="SUCCEEDED", choices=[("PENDING", "Kutilmoqda"), ("SUCCEEDED", "Tasdiqlangan"), ("FAILED", "Xato"), ("REFUNDED", "Qaytarilgan")])
    reconciliation_ref = models.CharField(max_length=64, blank=True)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payment_records"
        ordering = ["-created_at"]


class ReconciliationRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reconciliation_date = models.DateField()
    provider = models.CharField(max_length=40)
    zarvon_total_uzs = models.PositiveBigIntegerField()
    provider_total_uzs = models.PositiveBigIntegerField()
    difference_uzs = models.BigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=[("MATCHED", "Mos"), ("DISCREPANCY", "Farq bor"), ("RESOLVED", "Hal etildi")], default="MATCHED")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reconciliation_records"
        ordering = ["-reconciliation_date"]


class ExternalScoringReport(models.Model):
    """KATM (credit history & external loans), MIB enforcement debt & 50% DSTI burden report."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="external_scoring_reports")
    check_reference = models.CharField(max_length=48, unique=True, db_index=True)
    provider_mode = models.CharField(max_length=24, default="SANDBOX_ADAPTER")
    scenario_tag = models.CharField(max_length=32, default="auto")
    pinfl_masked = models.CharField(max_length=24, blank=True)
    inn_masked = models.CharField(max_length=24, blank=True)
    monthly_income_uzs = models.PositiveBigIntegerField(default=0)

    # MIB (Majburiy ijro byurosi)
    mib_status = models.CharField(
        max_length=16,
        default="CLEAN",
        choices=[("CLEAN", "Qarz yo‘q"), ("WARNING", "Kichik ijro/jarima"), ("BLOCKED", "Taqiqlangan ijro qarzi")],
    )
    mib_debt_uzs = models.PositiveBigIntegerField(default=0)
    mib_active_cases_count = models.PositiveIntegerField(default=0)
    mib_details = models.JSONField(default=list)

    # KATM (Kredit byurosi — boshqa bank/nasiya kreditlari)
    katm_score = models.PositiveIntegerField(default=710)
    external_active_credits_count = models.PositiveIntegerField(default=0)
    external_total_debt_uzs = models.PositiveBigIntegerField(default=0)
    external_monthly_obligations_uzs = models.PositiveBigIntegerField(default=0)
    external_overdue_days_max = models.PositiveIntegerField(default=0)
    external_credit_history_grade = models.CharField(max_length=8, default="A")
    external_obligations_breakdown = models.JSONField(default=list)

    # Markaziy bank DSTI <= 50% (Qarz yuki)
    zarvon_active_monthly_uzs = models.PositiveBigIntegerField(default=0)
    projected_new_monthly_uzs = models.PositiveBigIntegerField(default=0)
    dsti_before_pct = models.FloatField(default=0.0)
    dsti_after_pct = models.FloatField(default=0.0)
    max_safe_monthly_uzs = models.PositiveBigIntegerField(default=0)
    recommended_limit_uzs = models.PositiveBigIntegerField(default=0)
    decision = models.CharField(
        max_length=24,
        default="APPROVE",
        choices=[("APPROVE", "Tasdiqlandi"), ("MANUAL_REVIEW", "Qo‘shimcha ko‘rik"), ("DECLINE", "Rad etildi")],
    )
    decision_reasons = models.JSONField(default=list)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "external_scoring_reports"
        ordering = ["-created_at"]


class PaymentCard(models.Model):
    """Tokenized Uzcard/Humo/Visa card — stores encrypted PSP token + masked PAN only (no raw PAN/CVV)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_cards")
    provider = models.CharField(
        max_length=24,
        choices=[("Payme", "Payme"), ("Click", "Click"), ("Uzum Bank", "Uzum Bank"), ("Uzcard/Humo", "Uzcard/Humo")],
        default="Uzcard/Humo",
    )
    card_brand = models.CharField(max_length=20, default="Uzcard")
    card_token_encrypted = models.TextField()
    card_masked_pan = models.CharField(max_length=24)
    expiry_masked = models.CharField(max_length=8, default="**/28")
    card_holder = models.CharField(max_length=120, blank=True)
    is_verified = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    auto_debit_enabled = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payment_cards"
        ordering = ["-is_default", "-created_at"]


class PspTransaction(models.Model):
    """Protocol-accurate transaction log for Click (Prepare/Complete) & Payme (JSON-RPC 2.0) & Uzum/Paynet."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    psp_provider = models.CharField(max_length=32, db_index=True)  # Click, Payme, Uzum Bank, Paynet
    external_trans_id = models.CharField(max_length=96, db_index=True)
    merchant_trans_id = models.CharField(max_length=64, db_index=True)  # order_number or contract_number
    merchant_prepare_id = models.CharField(max_length=64, blank=True)
    action_stage = models.CharField(
        max_length=24,
        default="INITIATED",
        choices=[
            ("INITIATED", "Boshlangan"),
            ("PREPARED", "Prepare / Created"),
            ("PERFORMED", "To‘landi (Complete/Perform)"),
            ("CANCELLED", "Bekor qilindi"),
            ("FAILED", "Xato"),
        ],
    )
    amount_tiyin = models.BigIntegerField()  # 1 UZS = 100 tiyin
    state_code = models.IntegerField(default=1)  # Payme states: 1 created, 2 performed, -1/-2 cancelled
    signature_verified = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=96, unique=True)
    order = models.ForeignKey("commerce.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="psp_transactions")
    contract = models.ForeignKey(InstallmentContract, on_delete=models.SET_NULL, null=True, blank=True, related_name="psp_transactions")
    raw_payload_sanitized = models.JSONField(default=dict)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "psp_transactions"
        ordering = ["-created_at"]


class PaymentReminderLog(models.Model):
    """Audit trail of upcoming payment & overdue alerts sent to customers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(InstallmentContract, on_delete=models.CASCADE, related_name="reminder_logs")
    schedule_item = models.ForeignKey(InstallmentScheduleItem, on_delete=models.CASCADE, related_name="reminder_logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_reminders")
    window_tag = models.CharField(
        max_length=20,
        choices=[
            ("DUE_7_DAYS", "7 kun qoldi"),
            ("DUE_3_DAYS", "3 kun qoldi"),
            ("DUE_1_DAY", "1 kun qoldi"),
            ("DUE_TODAY", "Bugun to‘lov kuni"),
            ("OVERDUE", "Muddati o‘tgan"),
        ],
    )
    channel = models.CharField(max_length=20, default="SMS")
    amount_due_uzs = models.PositiveBigIntegerField()
    due_date = models.DateField()
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_reminders")
    status = models.CharField(max_length=24, default="SENT")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payment_reminder_logs"
        ordering = ["-created_at"]
