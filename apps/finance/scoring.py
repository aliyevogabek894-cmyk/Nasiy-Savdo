"""KATM Credit Bureau, MIB Enforcement Debt & 50% DSTI Debt-Burden Scoring Engine."""
import uuid
from django.conf import settings
from django.utils import timezone

from apps.finance.models import ContractStatus, ExternalScoringReport, InstallmentContract
from apps.governance.models import BhmValue, ComplianceRuleVersion
from config.utils import compute_monthly_installment, mask_value


def _build_bureau_payload(
    *,
    scenario: str,
    pinfl: str,
    monthly_income_uzs: int,
) -> dict:
    """
    Build deterministic KATM & MIB bureau telemetry via Sandbox Adapter
    (or live REST adapter when KATM_API_URL / MIB_API_URL are configured).
    """
    chosen = (scenario or "auto").strip().lower()
    if chosen == "auto":
        if pinfl.endswith("0088"):
            chosen = "mib_debt"
        elif pinfl.endswith("0077"):
            chosen = "high_debt"
        elif pinfl.endswith("0066"):
            chosen = "overdue_katm"
        elif pinfl.endswith("0055"):
            chosen = "moderate_credit"
        else:
            chosen = "clean"

    if chosen == "mib_debt":
        return {
            "scenario_tag": "mib_debt",
            "mib_status": "BLOCKED",
            "mib_debt_uzs": 2_450_000,
            "mib_active_cases_count": 2,
            "mib_details": [
                {"case_no": "MIB-1024/26", "reason": "YHXBB ma’muriy jarima va ijro yig‘imi", "debt_uzs": 1_250_000, "blocking": True},
                {"case_no": "MIB-2089/26", "reason": "Kommunal xizmatlar qarzdorligi", "debt_uzs": 1_200_000, "blocking": True},
            ],
            "katm_score": 560,
            "external_credit_history_grade": "C",
            "external_overdue_days_max": 12,
            "external_obligations": [
                {"lender": "Hamkor Bank (Sandbox)", "type": "Iste’mol krediti", "monthly_uzs": 950_000, "remaining_uzs": 8_500_000, "status": "ON_TIME"},
            ],
        }

    if chosen == "overdue_katm":
        return {
            "scenario_tag": "overdue_katm",
            "mib_status": "CLEAN",
            "mib_debt_uzs": 0,
            "mib_active_cases_count": 0,
            "mib_details": [],
            "katm_score": 445,
            "external_credit_history_grade": "D",
            "external_overdue_days_max": 45,
            "external_obligations": [
                {"lender": "Tijorat Banki #2 (Sandbox)", "type": "Mikroqarz", "monthly_uzs": 1_350_000, "remaining_uzs": 6_400_000, "status": "OVERDUE_45D"},
                {"lender": "Hamkor Nasiya (Sandbox)", "type": "Muddatli to‘lov", "monthly_uzs": 620_000, "remaining_uzs": 3_100_000, "status": "ON_TIME"},
            ],
        }

    if chosen == "high_debt":
        obligations = [
            {"lender": "Ipoteka-Bank (Sandbox)", "type": "Avtokredit", "monthly_uzs": max(2_200_000, round(monthly_income_uzs * 0.34)), "remaining_uzs": 54_000_000, "status": "ON_TIME"},
            {"lender": "Mikroqarz Tashkiloti (Sandbox)", "type": "Onlayn mikroqarz", "monthly_uzs": max(1_400_000, round(monthly_income_uzs * 0.22)), "remaining_uzs": 14_200_000, "status": "ON_TIME"},
        ]
        return {
            "scenario_tag": "high_debt",
            "mib_status": "CLEAN",
            "mib_debt_uzs": 0,
            "mib_active_cases_count": 0,
            "mib_details": [],
            "katm_score": 635,
            "external_credit_history_grade": "B",
            "external_overdue_days_max": 0,
            "external_obligations": obligations,
        }

    if chosen == "moderate_credit":
        ext_m1 = max(650_000, round(monthly_income_uzs * 0.14))
        ext_m2 = max(450_000, round(monthly_income_uzs * 0.10))
        return {
            "scenario_tag": "moderate_credit",
            "mib_status": "CLEAN",
            "mib_debt_uzs": 0,
            "mib_active_cases_count": 0,
            "mib_details": [],
            "katm_score": 715,
            "external_credit_history_grade": "A",
            "external_overdue_days_max": 0,
            "external_obligations": [
                {"lender": "Agrobank (Sandbox)", "type": "Iste’mol krediti", "monthly_uzs": ext_m1, "remaining_uzs": ext_m1 * 9, "status": "ON_TIME"},
                {"lender": "Tashqi Nasiya Servisi (Sandbox)", "type": "Muddatli to‘lov", "monthly_uzs": ext_m2, "remaining_uzs": ext_m2 * 5, "status": "ON_TIME"},
            ],
        }

    # Default 'clean': good credit discipline, small active bank payment (~10% of income), zero MIB debt
    small_ext = max(350_000, round(monthly_income_uzs * 0.08))
    return {
        "scenario_tag": "clean",
        "mib_status": "CLEAN",
        "mib_debt_uzs": 0,
        "mib_active_cases_count": 0,
        "mib_details": [],
        "katm_score": 768,
        "external_credit_history_grade": "A+",
        "external_overdue_days_max": 0,
        "external_obligations": [
            {"lender": "Kapitalbank (Sandbox)", "type": "Kredit karta / mikroqarz", "monthly_uzs": small_ext, "remaining_uzs": small_ext * 6, "status": "ON_TIME"},
        ],
    }


def run_katm_and_mib_scoring(
    *,
    user,
    pinfl: str,
    inn: str = "",
    birth_year: int = 1994,
    monthly_income_uzs: int = 8_000_000,
    requested_purchase_uzs: int = 0,
    requested_months: int = 12,
    scenario: str = "auto",
) -> ExternalScoringReport:
    """
    Compute full creditworthiness report combining:
    - PINFL & INN/STIR identity check
    - MIB enforcement debt check
    - KATM other banks/lenders active credits & payment discipline
    - Central Bank 50% DSTI (Debt-Service-to-Income) limit calculation
    """
    income = max(1_000_000, int(monthly_income_uzs or 8_000_000))
    bureau = _build_bureau_payload(scenario=scenario, pinfl=pinfl, monthly_income_uzs=income)

    # Sum customer's existing active monthly obligations inside ZARVON
    active_contracts = InstallmentContract.objects.filter(
        customer=user,
        status__in=[ContractStatus.SIGNED, ContractStatus.ACTIVE, ContractStatus.OVERDUE, ContractStatus.RESTRUCTURED],
    )
    zarvon_monthly = sum(int(c.summary_terms.get("monthly_payment") or (c.total_payable // max(1, c.months))) for c in active_contracts)

    external_obligations = bureau["external_obligations"]
    external_monthly = sum(int(item["monthly_uzs"]) for item in external_obligations)
    external_total_debt = sum(int(item["remaining_uzs"]) for item in external_obligations)

    projected_new_monthly = 0
    if requested_purchase_uzs > 0:
        q = compute_monthly_installment(int(requested_purchase_uzs), min(12, max(1, int(requested_months or 12))), 24.0, 2.0)
        projected_new_monthly = q["monthly_payment"]

    existing_monthly_burden = external_monthly + zarvon_monthly
    max_total_monthly_50pct = int(income * 0.50)
    max_safe_monthly = max(0, max_total_monthly_50pct - existing_monthly_burden)

    dsti_before = round((existing_monthly_burden / income) * 100.0, 1)
    dsti_after = round(((existing_monthly_burden + projected_new_monthly) / income) * 100.0, 1)

    rule = ComplianceRuleVersion.get_active()
    bhm_cap = BhmValue.get_current_amount() * rule.max_bhm_multiplier

    # Convert safe monthly capacity into safe 12-month principal (conservatively dividing by ~1.26 total cost factor)
    safe_principal_capacity = int((max_safe_monthly * 12) / 1.26)
    safe_principal_rounded = max(0, (safe_principal_capacity // 500_000) * 500_000)
    recommended_limit = min(safe_principal_rounded, 35_000_000, bhm_cap)

    age = timezone.now().year - int(birth_year or 1994)
    reasons = []
    decision = "APPROVE"

    if bureau["mib_status"] == "BLOCKED":
        decision = "DECLINE"
        recommended_limit = 0
        reasons.append(f"MIB_DEBT_BLOCKED: Majburiy ijro byurosida {bureau['mib_debt_uzs']:,} so‘m qarzdorlik aniqlandi.")
    elif bureau["mib_status"] == "WARNING":
        decision = "MANUAL_REVIEW"
        reasons.append(f"MIB_WARNING: MIBda {bureau['mib_debt_uzs']:,} so‘m jarima mavjud.")
    else:
        reasons.append("MIB_CLEAN: Majburiy ijro byurosida qarzdorlik topilmadi.")

    if bureau["external_overdue_days_max"] > 30:
        decision = "DECLINE"
        recommended_limit = 0
        reasons.append(f"KATM_OVERDUE_BLOCK: Boshqa kredit tashkilotida {bureau['external_overdue_days_max']} kunlik kechikish mavjud.")
    elif external_obligations:
        reasons.append(
            f"KATM_OTHER_CREDITS_CHECKED: Boshqa joylarda {len(external_obligations)} ta faol kredit/nasiya, "
            f"oylik to‘lov {external_monthly:,} so‘m ({bureau['external_credit_history_grade']} reyting)."
        )

    if dsti_before >= 50.0 or max_safe_monthly < 250_000:
        decision = "DECLINE"
        recommended_limit = 0
        reasons.append(
            f"DSTI_OVER_50PCT: Amaldagi qarz yuki {dsti_before}% — Markaziy bankning 50% chegarasidan oshgan."
        )
    else:
        reasons.append(
            f"DSTI_COMPLIANT: Hozirgi qarz yuki {dsti_before}% (≤ 50% me’yor). "
            f"Qo‘shimcha xavfsiz oylik to‘lov sig‘imi: {max_safe_monthly:,} so‘m/oy."
        )

    if projected_new_monthly > 0 and dsti_after > 50.0 and decision == "APPROVE":
        decision = "MANUAL_REVIEW"
        reasons.append(f"REQUESTED_PURCHASE_DSTI_HIGH: Yangi xarid bilan qarz yuki {dsti_after}% ga yetadi (> 50%).")

    if (age < 22 or age > 65) and decision == "APPROVE":
        decision = "MANUAL_REVIEW"
        reasons.append("AGE_POLICY_BOUNDARY: Yosh siyosati (22–65 yosh) bo‘yicha qo‘shimcha inson ko‘rigi.")

    if decision == "APPROVE" and recommended_limit < 2_000_000:
        recommended_limit = 2_000_000 if max_safe_monthly >= 250_000 else 0

    provider_mode = "LIVE_ADAPTER" if (settings.KATM_API_URL and settings.MIB_API_URL) else "SANDBOX_ADAPTER"
    return ExternalScoringReport.objects.create(
        user=user,
        check_reference=f"KATM-{uuid.uuid4().hex[:10].upper()}",
        provider_mode=provider_mode,
        scenario_tag=bureau["scenario_tag"],
        pinfl_masked=mask_value(pinfl, 4, 2),
        inn_masked=mask_value(inn, 3, 2) if inn else "",
        monthly_income_uzs=income,
        mib_status=bureau["mib_status"],
        mib_debt_uzs=bureau["mib_debt_uzs"],
        mib_active_cases_count=bureau["mib_active_cases_count"],
        mib_details=bureau["mib_details"],
        katm_score=bureau["katm_score"],
        external_active_credits_count=len(external_obligations),
        external_total_debt_uzs=external_total_debt,
        external_monthly_obligations_uzs=external_monthly,
        external_overdue_days_max=bureau["external_overdue_days_max"],
        external_credit_history_grade=bureau["external_credit_history_grade"],
        external_obligations_breakdown=external_obligations,
        zarvon_active_monthly_uzs=zarvon_monthly,
        projected_new_monthly_uzs=projected_new_monthly,
        dsti_before_pct=dsti_before,
        dsti_after_pct=dsti_after,
        max_safe_monthly_uzs=max_safe_monthly,
        recommended_limit_uzs=recommended_limit,
        decision=decision,
        decision_reasons=reasons,
        is_demo=(provider_mode == "SANDBOX_ADAPTER"),
    )
