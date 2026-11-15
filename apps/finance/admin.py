"""Django Admin registrations for ZARVON payments, contracts, schedules, and reconciliation."""
from django.contrib import admin

from apps.finance.models import (
    CustomerLimit,
    ExternalScoringReport,
    InstallmentContract,
    InstallmentScheduleItem,
    PaymentCard,
    PaymentRecord,
    PspTransaction,
    ReconciliationRecord,
    RepaymentEvent,
)


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ("payment_intent_id", "provider", "user", "amount", "status", "reconciliation_ref", "is_demo", "created_at")
    list_filter = ("provider", "status", "is_demo", "created_at")
    search_fields = ("payment_intent_id", "reconciliation_ref", "user__phone", "user__full_name")
    readonly_fields = ("id", "created_at")


@admin.register(PspTransaction)
class PspTransactionAdmin(admin.ModelAdmin):
    list_display = ("psp_provider", "external_trans_id", "merchant_trans_id", "action_stage", "state_code", "amount_tiyin", "signature_verified", "created_at")
    list_filter = ("psp_provider", "action_stage", "signature_verified", "is_demo")
    search_fields = ("external_trans_id", "merchant_trans_id", "merchant_prepare_id", "idempotency_key")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(InstallmentContract)
class InstallmentContractAdmin(admin.ModelAdmin):
    list_display = ("contract_number", "customer", "provider_name", "months", "total_payable", "remaining_balance", "status", "created_at")
    list_filter = ("status", "provider_type", "months", "is_demo")
    search_fields = ("contract_number", "order__order_number", "customer__phone", "customer__full_name")
    readonly_fields = ("id", "created_at")


@admin.register(InstallmentScheduleItem)
class InstallmentScheduleItemAdmin(admin.ModelAdmin):
    list_display = ("contract", "installment_no", "due_date", "amount_due", "amount_paid", "penalty_amount", "status", "paid_at")
    list_filter = ("status", "due_date")
    search_fields = ("contract__contract_number",)
    readonly_fields = ("id",)


@admin.register(RepaymentEvent)
class RepaymentEventAdmin(admin.ModelAdmin):
    list_display = ("contract", "amount", "payment_method", "is_early_repayment", "early_fee", "idempotency_key", "created_at")
    list_filter = ("payment_method", "is_early_repayment")
    search_fields = ("contract__contract_number", "idempotency_key")
    readonly_fields = ("id", "created_at")


@admin.register(ReconciliationRecord)
class ReconciliationRecordAdmin(admin.ModelAdmin):
    list_display = ("reconciliation_date", "provider", "zarvon_total_uzs", "provider_total_uzs", "difference_uzs", "status")
    list_filter = ("provider", "status", "reconciliation_date")
    readonly_fields = ("id", "created_at")


@admin.register(CustomerLimit)
class CustomerLimitAdmin(admin.ModelAdmin):
    list_display = ("user", "tier", "total_limit_uzs", "used_limit_uzs", "is_frozen", "updated_at")
    list_filter = ("tier", "is_frozen", "is_demo_limit")
    search_fields = ("user__phone", "user__full_name")
    readonly_fields = ("id", "updated_at")


@admin.register(PaymentCard)
class PaymentCardAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "card_brand", "card_masked_pan", "expiry_masked", "is_default", "is_verified")
    list_filter = ("provider", "card_brand", "is_verified")
    search_fields = ("user__phone", "card_masked_pan")
    readonly_fields = ("id", "created_at")


@admin.register(ExternalScoringReport)
class ExternalScoringReportAdmin(admin.ModelAdmin):
    list_display = ("check_reference", "user", "katm_score", "mib_status", "dsti_after_pct", "recommended_limit_uzs", "decision", "created_at")
    list_filter = ("decision", "mib_status", "is_demo")
    search_fields = ("check_reference", "user__phone", "user__full_name")
    readonly_fields = ("id", "created_at")
