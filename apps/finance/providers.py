"""InstallmentProvider Abstraction & Compliance Guard (Sections 27.1, 28.1, 28.3)."""
from datetime import timedelta
import uuid
from django.utils import timezone
from config.utils import compute_monthly_installment
from apps.governance.models import BhmValue, ComplianceRuleVersion


class ComplianceViolationError(ValueError):
    """Raised when an installment configuration or transaction violates statutory limits."""


def validate_installment_compliance(*, principal: int, months: int, annual_markup_pct: float, commission_pct: float, category_installment_allowed: bool = True) -> dict:
    """Enforce 2027-01-01 Uzbekistan installment guardrails before saving/issuing."""
    rule = ComplianceRuleVersion.get_active()
    bhm_amount = BhmValue.get_current_amount()
    max_allowed_amount = bhm_amount * rule.max_bhm_multiplier

    if not category_installment_allowed:
        raise ComplianceViolationError("Ushbu toifadagi tovar/mulk uchun muddatli to‘lov qonunchilikka ko‘ra taqiqlangan (27.1).")
    if months < 1 or months > rule.max_months:
        raise ComplianceViolationError(f"Muddat {rule.max_months} oydan oshishi mumkin emas (so‘raldi: {months} oy).")
    if principal > max_allowed_amount:
        raise ComplianceViolationError(
            f"Nasiya summasi 250 BHM ({max_allowed_amount:,} so‘m) chegarasidan oshmasligi kerak."
        )
    calc = compute_monthly_installment(principal, months, annual_markup_pct, commission_pct)
    if not calc["within_50pct_cap"] or calc["annualized_extra_pct"] > rule.max_annual_extra_pct:
        raise ComplianceViolationError(
            f"Qo‘shimcha xarajatlar ({calc['annualized_extra_pct']}%) yillik {rule.max_annual_extra_pct}% chegarasidan oshdi."
        )
    calc["bhm_amount"] = bhm_amount
    calc["max_bhm_limit"] = max_allowed_amount
    calc["compliance_version"] = rule.version_code
    return calc


class BaseInstallmentProvider:
    provider_type = "BASE"

    def calculate_quote(self, *, principal: int, months: int, plan, category_allowed: bool = True) -> dict:
        raise NotImplementedError

    def submit_application(self, **kwargs):
        raise NotImplementedError


class OwnInstallmentProvider(BaseInstallmentProvider):
    """ZARVON Nasiya operator provider (uses Compliance Guard + InstallmentPlan)."""

    provider_type = "OWN_NASIYA"

    def calculate_quote(self, *, principal: int, months: int, plan, category_allowed: bool = True) -> dict:
        calc = validate_installment_compliance(
            principal=principal,
            months=months,
            annual_markup_pct=plan.annual_markup_pct,
            commission_pct=plan.commission_pct,
            category_installment_allowed=category_allowed,
        )
        calc["provider_type"] = self.provider_type
        calc["provider_label"] = "ZARVON Nasiya (Sandbox)"
        calc["is_indicative"] = True
        return calc

    def build_schedule(self, *, contract, start_date=None):
        from apps.finance.models import InstallmentScheduleItem

        start = start_date or (timezone.now().date() + timedelta(days=30))
        months = contract.months
        base_principal = contract.principal_amount // months
        rem_principal = contract.principal_amount - base_principal * months
        base_markup = (contract.markup_amount + contract.commission_amount) // months
        rem_markup = (contract.markup_amount + contract.commission_amount) - base_markup * months

        items = []
        for idx in range(1, months + 1):
            p_part = base_principal + (rem_principal if idx == months else 0)
            m_part = base_markup + (rem_markup if idx == months else 0)
            due = start + timedelta(days=30 * (idx - 1))
            items.append(
                InstallmentScheduleItem(
                    contract=contract,
                    installment_no=idx,
                    due_date=due,
                    principal_part=p_part,
                    markup_part=m_part,
                    amount_due=p_part + m_part,
                    status="UPCOMING",
                )
            )
        InstallmentScheduleItem.objects.bulk_create(items)
        return items


class PartnerFinanceProvider(BaseInstallmentProvider):
    """Multi-Bank Sandbox Gateway Adapter — resilient to single-bank timeout/failure (Section 8.4)."""

    provider_type = "PARTNER_BANK"

    def dispatch_to_banks(self, *, credit_application, banks, base_correlation_id: str):
        from apps.finance.models import BankApplication, BankOffer

        results = []
        available_offers = 0
        for bank in banks:
            corr = f"{base_correlation_id}-{bank.code}"
            idem = f"bank-app-{credit_application.id}-{bank.code}"
            if bank.adapter_status == "TIMEOUT":
                # Single bank timeout must NOT block other banks or mark customer as credit-unworthy (8.4)
                ba = BankApplication.objects.create(
                    credit_application=credit_application,
                    bank=bank,
                    correlation_id=corr,
                    idempotency_key=idem,
                    status="Bank response pending",
                    error_message="Bank API vaqtincha javob bermadi (timeout). Boshqa banklar davom etmoqda.",
                )
                results.append({"bank": bank.name, "status": ba.status, "error": ba.error_message})
                continue

            months = min(credit_application.requested_months, bank.max_months, 12)
            calc = compute_monthly_installment(
                credit_application.requested_amount,
                months,
                bank.base_annual_rate_pct,
                1.5,
            )
            ba = BankApplication.objects.create(
                credit_application=credit_application,
                bank=bank,
                correlation_id=corr,
                idempotency_key=idem,
                status="Offer Available",
                responded_at=timezone.now(),
            )
            offer = BankOffer.objects.create(
                bank_application=ba,
                bank=bank,
                principal_amount=credit_application.requested_amount,
                down_payment=0,
                months=months,
                annual_rate_pct=bank.base_annual_rate_pct,
                total_cost_of_credit_pct=calc["annualized_extra_pct"],
                mandatory_commission=calc["commission_amount"],
                monthly_payment=calc["monthly_payment"],
                total_payable=calc["total_payable"],
                expires_at=timezone.now() + timedelta(days=3),
                is_demo=True,
            )
            available_offers += 1
            results.append({"bank": bank.name, "status": "Offer Available", "offer_id": str(offer.id)})

        credit_application.status = "Offer Available" if available_offers > 0 else "Bank Pending"
        credit_application.save(update_fields=["status"])
        return results
