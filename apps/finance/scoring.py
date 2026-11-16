"""KATM Credit Bureau, MIB Enforcement Debt & 50% DSTI Debt-Burden Scoring Engine."""
import logging
import time
import uuid
import requests
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.finance.models import (
    ContractStatus,
    CustomerLimit,
    ExternalScoringReport,
    InstallmentContract,
    InstallmentScheduleItem,
    KycDocument,
)
from apps.governance.models import BhmValue, ComplianceRuleVersion, NotificationEvent, SecurityEvent
from config.utils import compute_monthly_installment, mask_value

logger = logging.getLogger(__name__)

SUPERVISOR_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.RISK_MANAGER,
    UserRole.AUDITOR,
    UserRole.FINANCE_OFFICER,
    UserRole.FRAUD_ANALYST,
]


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

    if chosen in {"moderate_credit", "has_credit", "active_credit"}:
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

    # Default 'clean': zero active credits, zero overdue, zero MIB debt -> eligible for Nasiya
    return {
        "scenario_tag": "clean",
        "mib_status": "CLEAN",
        "mib_debt_uzs": 0,
        "mib_active_cases_count": 0,
        "mib_details": [],
        "katm_score": 785,
        "external_credit_history_grade": "A+",
        "external_overdue_days_max": 0,
        "external_obligations": [],
    }


def verify_myid_liveness(*, pinfl: str, passport: str, birth_year: int, liveness_passed: bool = True) -> dict:
    """Verify passport/PINFL via MyID Biometric REST API when configured, or return simulated MyID HTTP trace."""
    api_url = (getattr(settings, "MYID_API_URL", "") or "").strip()
    pinfl_m = mask_value(pinfl, 4, 2)
    pass_m = mask_value(passport, 2, 2)
    if api_url:
        t0 = time.monotonic()
        headers = {}
        secret = getattr(settings, "MYID_CLIENT_SECRET", "") or ""
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        try:
            resp = requests.post(
                api_url,
                headers=headers,
                json={
                    "client_id": getattr(settings, "MYID_CLIENT_ID", ""),
                    "pinfl": pinfl,
                    "passport": passport,
                    "birth_year": int(birth_year or 1994),
                    "liveness_check": bool(liveness_passed),
                },
                timeout=8,
            )
            ms = round((time.monotonic() - t0) * 1000)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            ok = bool(data.get("verified", liveness_passed))
            return {
                "verified": ok,
                "mode": "LIVE_HTTP",
                "trace": {
                    "service": "MyID Biometric",
                    "mode": "LIVE_HTTP",
                    "endpoint": api_url,
                    "http_status": resp.status_code,
                    "latency_ms": ms,
                    "request_masked": {"pinfl": pinfl_m, "passport": pass_m, "birth_year": int(birth_year or 1994)},
                    "response_summary": {"verified": ok, "liveness": bool(data.get("liveness_passed", ok))},
                },
            }
        except Exception as exc:
            ms = round((time.monotonic() - t0) * 1000)
            logger.warning("MyID LIVE_HTTP xatosi: %s", exc)
            return {
                "verified": False,
                "mode": "LIVE_HTTP_ERROR",
                "trace": {
                    "service": "MyID Biometric",
                    "mode": "LIVE_HTTP_ERROR",
                    "endpoint": api_url,
                    "http_status": 502,
                    "latency_ms": ms,
                    "request_masked": {"pinfl": pinfl_m, "passport": pass_m},
                    "error": str(exc)[:180],
                },
            }

    return {
        "verified": bool(liveness_passed),
        "mode": "SANDBOX_HTTP_SIM",
        "trace": {
            "service": "MyID Biometric",
            "mode": "SANDBOX_HTTP_SIM",
            "endpoint": "https://api.myid.uz/api/v1/authentication/verify (Simulated)",
            "http_status": 200,
            "latency_ms": 18,
            "request_masked": {"pinfl": pinfl_m, "passport": pass_m, "birth_year": int(birth_year or 1994)},
            "response_summary": {"verified": bool(liveness_passed), "face_match_pct": 98.6},
        },
    }


def query_katm_and_mib_bureau(
    *,
    scenario: str,
    pinfl: str,
    inn: str = "",
    passport: str = "",
    birth_year: int = 1994,
    monthly_income_uzs: int = 8_000_000,
    liveness_passed: bool = True,
) -> dict:
    """
    Query MyID + KATM + MIB REST services via live HTTPS POST when configured in env,
    or execute deterministic Sandbox HTTP-protocol simulation when URLs are unset.
    """
    sim_payload = _build_bureau_payload(scenario=scenario, pinfl=pinfl, monthly_income_uzs=monthly_income_uzs)
    myid_res = verify_myid_liveness(
        pinfl=pinfl,
        passport=passport,
        birth_year=birth_year,
        liveness_passed=liveness_passed,
    )
    traces = [myid_res["trace"]]

    pinfl_m = mask_value(pinfl, 4, 2)
    inn_m = mask_value(inn, 3, 2) if inn else ""
    katm_url = (getattr(settings, "KATM_API_URL", "") or "").strip()
    mib_url = (getattr(settings, "MIB_API_URL", "") or "").strip()
    live_used = False
    bureau_error = False

    # KATM Query
    katm_data = None
    if katm_url:
        live_used = True
        t0 = time.monotonic()
        headers = {}
        k_tok = getattr(settings, "KATM_API_TOKEN", "") or ""
        if k_tok:
            headers["Authorization"] = f"Bearer {k_tok}"
        try:
            resp = requests.post(
                katm_url,
                headers=headers,
                json={"pinfl": pinfl, "inn": inn, "passport": passport},
                timeout=8,
            )
            ms = round((time.monotonic() - t0) * 1000)
            resp.raise_for_status()
            katm_data = resp.json() if resp.content else {}
            traces.append(
                {
                    "service": "KATM (infokredit.uz)",
                    "mode": "LIVE_HTTP",
                    "endpoint": katm_url,
                    "http_status": resp.status_code,
                    "latency_ms": ms,
                    "request_masked": {"pinfl": pinfl_m, "inn": inn_m},
                    "response_summary": {
                        "katm_score": katm_data.get("katm_score"),
                        "obligations_count": len(katm_data.get("external_obligations") or []),
                        "overdue_days_max": katm_data.get("external_overdue_days_max", 0),
                    },
                }
            )
        except Exception as exc:
            ms = round((time.monotonic() - t0) * 1000)
            bureau_error = True
            logger.warning("KATM LIVE_HTTP xatosi: %s", exc)
            traces.append(
                {
                    "service": "KATM (infokredit.uz)",
                    "mode": "LIVE_HTTP_ERROR",
                    "endpoint": katm_url,
                    "http_status": 502,
                    "latency_ms": ms,
                    "request_masked": {"pinfl": pinfl_m, "inn": inn_m},
                    "error": str(exc)[:180],
                }
            )
    else:
        katm_data = {
            "katm_score": sim_payload["katm_score"],
            "external_credit_history_grade": sim_payload["external_credit_history_grade"],
            "external_overdue_days_max": sim_payload["external_overdue_days_max"],
            "external_obligations": sim_payload["external_obligations"],
        }
        traces.append(
            {
                "service": "KATM (infokredit.uz)",
                "mode": "SANDBOX_HTTP_SIM",
                "endpoint": "https://api.infokredit.uz/v1/credit-history (Simulated)",
                "http_status": 200,
                "latency_ms": 24,
                "request_masked": {"pinfl": pinfl_m, "inn": inn_m},
                "response_summary": {
                    "katm_score": katm_data["katm_score"],
                    "obligations_count": len(katm_data["external_obligations"]),
                    "overdue_days_max": katm_data["external_overdue_days_max"],
                },
            }
        )

    # MIB Query
    mib_data = None
    if mib_url:
        live_used = True
        t0 = time.monotonic()
        headers = {}
        m_tok = getattr(settings, "MIB_API_TOKEN", "") or ""
        if m_tok:
            headers["Authorization"] = f"Bearer {m_tok}"
        try:
            resp = requests.post(
                mib_url,
                headers=headers,
                json={"pinfl": pinfl},
                timeout=8,
            )
            ms = round((time.monotonic() - t0) * 1000)
            resp.raise_for_status()
            mib_data = resp.json() if resp.content else {}
            traces.append(
                {
                    "service": "MIB (mib.uz / api.my.gov.uz)",
                    "mode": "LIVE_HTTP",
                    "endpoint": mib_url,
                    "http_status": resp.status_code,
                    "latency_ms": ms,
                    "request_masked": {"pinfl": pinfl_m},
                    "response_summary": {
                        "mib_status": mib_data.get("mib_status", "CLEAN"),
                        "mib_debt_uzs": mib_data.get("mib_debt_uzs", 0),
                    },
                }
            )
        except Exception as exc:
            ms = round((time.monotonic() - t0) * 1000)
            bureau_error = True
            logger.warning("MIB LIVE_HTTP xatosi: %s", exc)
            traces.append(
                {
                    "service": "MIB (mib.uz / api.my.gov.uz)",
                    "mode": "LIVE_HTTP_ERROR",
                    "endpoint": mib_url,
                    "http_status": 502,
                    "latency_ms": ms,
                    "request_masked": {"pinfl": pinfl_m},
                    "error": str(exc)[:180],
                }
            )
    else:
        mib_data = {
            "mib_status": sim_payload["mib_status"],
            "mib_debt_uzs": sim_payload["mib_debt_uzs"],
            "mib_active_cases_count": sim_payload["mib_active_cases_count"],
            "mib_details": sim_payload["mib_details"],
        }
        traces.append(
            {
                "service": "MIB (mib.uz / api.my.gov.uz)",
                "mode": "SANDBOX_HTTP_SIM",
                "endpoint": "https://api.my.gov.uz/mib/v1/enforcement-debt (Simulated)",
                "http_status": 200,
                "latency_ms": 21,
                "request_masked": {"pinfl": pinfl_m},
                "response_summary": {
                    "mib_status": mib_data["mib_status"],
                    "mib_debt_uzs": mib_data["mib_debt_uzs"],
                },
            }
        )

    katm_safe = katm_data or {}
    mib_safe = mib_data or {}
    return {
        "scenario_tag": "live_http" if live_used else sim_payload["scenario_tag"],
        "live_used": live_used,
        "bureau_error": bureau_error,
        "myid_verified": myid_res["verified"],
        "mib_status": mib_safe.get("mib_status", "CLEAN"),
        "mib_debt_uzs": int(mib_safe.get("mib_debt_uzs") or 0),
        "mib_active_cases_count": int(mib_safe.get("mib_active_cases_count") or 0),
        "mib_details": mib_safe.get("mib_details") or [],
        "katm_score": int(katm_safe.get("katm_score") or 650),
        "external_credit_history_grade": str(katm_safe.get("external_credit_history_grade") or "B"),
        "external_overdue_days_max": int(katm_safe.get("external_overdue_days_max") or 0),
        "external_obligations": katm_safe.get("external_obligations") or [],
        "bureau_trace": traces,
    }


def _inspect_zarvon_credit_state(user) -> dict:
    """Inspect active ZARVON installment contracts and unpaid/overdue schedule rows."""
    today = timezone.localdate()
    active_contracts = list(
        InstallmentContract.objects.filter(
            customer=user,
            status__in=[
                ContractStatus.SIGNED,
                ContractStatus.ACTIVE,
                ContractStatus.OVERDUE,
                ContractStatus.RESTRUCTURED,
                ContractStatus.ASSIGNED,
            ],
        ).prefetch_related("schedule_items")
    )
    monthly_uzs = 0
    remaining_uzs = 0
    overdue_count = 0
    overdue_amount_uzs = 0
    overdue_max_days = 0
    contracts_summary = []

    for c in active_contracts:
        m_pay = int(c.summary_terms.get("monthly_payment") or (c.total_payable // max(1, c.months)))
        monthly_uzs += m_pay
        remaining_uzs += int(c.remaining_balance or 0)
        c_overdue_days = 0
        c_overdue_amt = 0

        for item in c.schedule_items.all():
            unpaid = max(0, int(item.amount_due or 0) + int(item.penalty_amount or 0) - int(item.amount_paid or 0))
            if unpaid <= 0:
                continue
            is_overdue = item.status == "OVERDUE" or (item.status in {"UPCOMING", "PARTIAL"} and item.due_date < today)
            if is_overdue:
                overdue_count += 1
                overdue_amount_uzs += unpaid
                c_overdue_amt += unpaid
                days = max(1, (today - item.due_date).days)
                overdue_max_days = max(overdue_max_days, days)
                c_overdue_days = max(c_overdue_days, days)

        if c.status in {ContractStatus.OVERDUE, ContractStatus.WRITTEN_OFF} and c_overdue_days == 0:
            overdue_count += 1
            c_overdue_days = 1
            overdue_max_days = max(overdue_max_days, 1)

        contracts_summary.append(
            {
                "contract_number": c.contract_number,
                "status": c.status,
                "remaining_balance_uzs": int(c.remaining_balance or 0),
                "monthly_payment_uzs": m_pay,
                "overdue_days": c_overdue_days,
                "overdue_amount_uzs": c_overdue_amt,
            }
        )

    return {
        "active_count": len(active_contracts),
        "monthly_uzs": monthly_uzs,
        "remaining_uzs": remaining_uzs,
        "overdue_count": overdue_count,
        "overdue_amount_uzs": overdue_amount_uzs,
        "overdue_max_days": overdue_max_days,
        "contracts_summary": contracts_summary,
    }


def evaluate_customer_credit_policy(user) -> dict:
    """
    Evaluate customer's live credit presence & condition across ZARVON + KATM + MIB.
    Policy: any active credit, overdue payment, or MIB enforcement debt restricts customer to Cash-Only (`DIRECT_PAY`).
    """
    z = _inspect_zarvon_credit_state(user)
    ext = ExternalScoringReport.objects.filter(user=user).first()
    lim = CustomerLimit.objects.filter(user=user).first()
    manual_cash_only = KycDocument.objects.filter(user=user, status="CASH_ONLY").exists() or bool(
        lim and lim.is_frozen and ("naqd" in (lim.freeze_reason or "").lower() or "kredit" in (lim.freeze_reason or "").lower())
    )

    ext_active_count = int(ext.external_active_credits_count or 0) if ext else 0
    ext_total_debt = int(ext.external_total_debt_uzs or 0) if ext else 0
    ext_monthly = int(ext.external_monthly_obligations_uzs or 0) if ext else 0
    ext_overdue_days = int(ext.external_overdue_days_max or 0) if ext else 0
    ext_grade = ext.external_credit_history_grade if ext else "—"
    katm_score = int(ext.katm_score or 0) if ext else 0
    mib_status = ext.mib_status if ext else "UNCHECKED"
    mib_debt = int(ext.mib_debt_uzs or 0) if ext else 0
    mib_cases = int(ext.mib_active_cases_count or 0) if ext else 0

    total_active_credits = z["active_count"] + ext_active_count
    total_monthly = z["monthly_uzs"] + ext_monthly
    has_overdue = z["overdue_count"] > 0 or ext_overdue_days > 0
    has_mib_debt = mib_status == "BLOCKED" or mib_debt > 0
    has_active_credit = total_active_credits > 0
    cash_only_required = has_overdue or has_mib_debt or has_active_credit or manual_cash_only or (ext is not None and ext.decision == "DECLINE")

    max_od_days = max(z["overdue_max_days"], ext_overdue_days)
    block_reason = ""
    if has_overdue:
        code = "OVERDUE_BLOCKED"
        label = f"⛔ Kechikkan krediti bor ({max_od_days} kun)"
        detail = (
            f"Mijozda kechikkan to‘lov aniqlandi (maks. {max_od_days} kun; "
            f"ZARVON kechikkan qism: {z['overdue_amount_uzs']:,} so‘m). Nasiya yopildi."
        )
        trading_mode = "Faqat naqd savdo (Nasiya yopiq)"
        block_reason = f"Kechikkan kreditingiz ({max_od_days} kun) mavjudligi sababli muddatli to‘lov cheklangan — faqat naqd yoki karta orqali xarid qilishingiz mumkin."
    elif has_mib_debt:
        code = "MIB_DEBT_BLOCKED"
        label = f"⛔ MIB ijro qarzi bor ({mib_debt:,} so‘m)"
        detail = f"Majburiy ijro byurosida {mib_cases} ta ijro ishi ({mib_debt:,} so‘m qarz) mavjud."
        trading_mode = "Faqat naqd savdo (Nasiya yopiq)"
        block_reason = f"MIB ijro qarzdorligi ({mib_debt:,} so‘m) aniqlangani sababli faqat naqd yoki karta bilan savdo qilish mumkin."
    elif has_active_credit:
        code = "ACTIVE_CREDIT_CASH_ONLY"
        label = f"⚠ Faol krediti bor ({total_active_credits} ta — o‘z vaqtida to‘lanmoqda)"
        detail = (
            f"Mijozda {total_active_credits} ta faol kredit/nasiya mavjud "
            f"(ZARVON: {z['active_count']} ta, KATM boshqa joylar: {ext_active_count} ta, oylik jami: {total_monthly:,} so‘m)."
        )
        trading_mode = "Faqat naqd savdo (Nasiya cheklangan)"
        block_reason = f"Sizda {total_active_credits} ta faol kredit (oylik {total_monthly:,} so‘m) mavjudligi sababli qo‘shimcha nasiya berilmaydi — faqat naqd savdo qila olasiz."
    elif manual_cash_only:
        code = "MANUAL_CASH_ONLY"
        label = "⚠ Nazoratchi tekshiruvi: Faqat naqd savdo"
        detail = (lim.freeze_reason if lim and lim.freeze_reason else "") or "Nazoratchi hujjat/kredit tekshiruvi natijasiga ko‘ra nasiya cheklangan."
        trading_mode = "Faqat naqd savdo (Nasiya cheklangan)"
        block_reason = "Nazoratchi tekshiruvi natijasida sizga faqat naqd yoki karta orqali xarid qilish rejimi belgilangan."
    elif ext is not None and ext.decision == "DECLINE":
        code = "DSTI_DECLINED_CASH_ONLY"
        label = f"⚠ Qarz yuki yuqori (DSTI {ext.dsti_before_pct}%)"
        detail = (ext.decision_reasons or ["DSTI cheklovi sababli nasiya rad etilgan."])[0]
        trading_mode = "Faqat naqd savdo (Nasiya cheklangan)"
        block_reason = "Skoring qaroriga ko‘ra muddatli to‘lov cheklangan — faqat naqd yoki karta bilan savdo mumkin."
    else:
        code = "CLEAN_NO_CREDIT" if ext else "UNVERIFIED_NO_CREDIT"
        label = "✓ Krediti yo‘q — toza tarix" if ext else "✓ Faol krediti aniqlanmagan (tekshiruv kutilmoqda)"
        detail = "Platforma va KATM byurosida faol kredit, kechikish yoki MIB qarzi topilmadi."
        trading_mode = "Nasiya va naqd savdo ochiq"

    return {
        "has_scoring_report": bool(ext),
        "check_reference": ext.check_reference if ext else "",
        "has_active_credit": has_active_credit,
        "has_overdue": has_overdue,
        "has_mib_debt": has_mib_debt,
        "cash_only_required": cash_only_required,
        "installment_allowed": not cash_only_required,
        "credit_condition_code": code,
        "credit_condition_label": label,
        "credit_condition_detail": detail,
        "trading_mode_label": trading_mode,
        "block_reason": block_reason,
        "zarvon_active_count": z["active_count"],
        "zarvon_remaining_uzs": z["remaining_uzs"],
        "zarvon_monthly_uzs": z["monthly_uzs"],
        "zarvon_overdue_count": z["overdue_count"],
        "zarvon_overdue_amount_uzs": z["overdue_amount_uzs"],
        "zarvon_overdue_max_days": z["overdue_max_days"],
        "zarvon_contracts_summary": z["contracts_summary"],
        "external_active_count": ext_active_count,
        "external_total_debt_uzs": ext_total_debt,
        "external_monthly_uzs": ext_monthly,
        "external_overdue_days_max": ext_overdue_days,
        "external_grade": ext_grade,
        "external_obligations_breakdown": ext.external_obligations_breakdown if ext else [],
        "katm_score": katm_score,
        "mib_status": mib_status,
        "mib_debt_uzs": mib_debt,
        "mib_active_cases_count": mib_cases,
        "mib_details": ext.mib_details if ext else [],
        "dsti_before_pct": ext.dsti_before_pct if ext else 0.0,
        "dsti_after_pct": ext.dsti_after_pct if ext else 0.0,
        "total_active_credits": total_active_credits,
        "total_monthly_obligations_uzs": total_monthly,
    }


def notify_supervisors_credit_status(
    *,
    user,
    policy: dict,
    ext_report=None,
    trigger: str = "SCORING_CHECK",
    extra_note: str = "",
) -> int:
    """Send structured credit condition alert to all active Supervisors/Auditors/Risk Managers."""
    supervisors = list(User.objects.filter(role__in=SUPERVISOR_ROLES, is_active=True))
    if not supervisors:
        return 0

    ref = (ext_report.check_reference if ext_report else "") or f"CHK-{uuid.uuid4().hex[:8].upper()}"
    masked_phone = mask_value(user.phone or "", 4, 2)
    pinfl_mask = ext_report.pinfl_masked if ext_report else (mask_value(user.pinfl_hash or "", 2, 2) if user.pinfl_hash else "—")
    prefix = "⛔ NAZORATCHI OGOHLANTIRISHI" if (policy["has_overdue"] or policy["has_mib_debt"]) else ("⚠ NAZORATCHI XABARI" if policy["has_active_credit"] else "✅ NAZORATCHI HISOBOTI")
    title = f"{prefix}: {user.full_name} — {policy['credit_condition_label']}"
    if len(title) > 158:
        title = title[:155] + "..."

    trig_uz = {
        "SCORING_CHECK": "PINFL/KATM/MIB tekshiruvi",
        "SUPERVISOR_INSPECTION": "Nazoratchi tomonidan tekshirildi",
        "BLOCKED_NASIYA_CHECKOUT": "Kassada nasiya urinishi bloklandi",
    }.get(trigger, trigger)

    body = (
        f"[{trig_uz}] Mijoz: {user.full_name} ({masked_phone}, PINFL: {pinfl_mask}). "
        f"Kredit holati: {policy['credit_condition_detail']} "
        f"KATM: {policy['katm_score'] or '—'} ({policy['external_grade']}), MIB: {policy['mib_status']} ({policy['mib_debt_uzs']:,} so‘m). "
        f"Savdo rejimi: {policy['trading_mode_label']}."
    )
    if extra_note:
        body = f"{body} {extra_note}"

    corr = f"SUP-CREDIT:{policy['credit_condition_code']}:{ref}"
    NotificationEvent.objects.bulk_create(
        [
            NotificationEvent(
                user=sup,
                channel="PUSH",
                category="TRANSACTIONAL",
                status="delivered",
                title=title,
                body_masked=body,
                correlation_id=corr[:64],
            )
            for sup in supervisors
        ]
    )

    if policy["has_overdue"] or policy["has_mib_debt"] or trigger == "BLOCKED_NASIYA_CHECKOUT":
        SecurityEvent.objects.create(
            event_type=f"CREDIT_POLICY_{policy['credit_condition_code']}",
            severity="HIGH" if (policy["has_overdue"] or policy["has_mib_debt"]) else "MEDIUM",
            user=user,
            description=body,
            details={
                "trigger": trigger,
                "cash_only_required": policy["cash_only_required"],
                "total_active_credits": policy["total_active_credits"],
                "overdue_days": max(policy["zarvon_overdue_max_days"], policy["external_overdue_days_max"]),
                "mib_debt_uzs": policy["mib_debt_uzs"],
                "check_reference": ref,
            },
        )

    return len(supervisors)


def run_katm_and_mib_scoring(
    *,
    user,
    pinfl: str,
    inn: str = "",
    passport: str = "",
    birth_year: int = 1994,
    monthly_income_uzs: int = 8_000_000,
    requested_purchase_uzs: int = 0,
    requested_months: int = 12,
    scenario: str = "auto",
    liveness_passed: bool = True,
) -> ExternalScoringReport:
    """
    Compute full creditworthiness report combining:
    - MyID biometric / PINFL & INN/STIR identity check
    - MIB enforcement debt check
    - KATM other banks/lenders active credits & payment discipline
    - Central Bank 50% DSTI (Debt-Service-to-Income) limit calculation
    """
    income = max(1_000_000, int(monthly_income_uzs or 8_000_000))
    bureau = query_katm_and_mib_bureau(
        scenario=scenario,
        pinfl=pinfl,
        inn=inn,
        passport=passport,
        birth_year=birth_year,
        monthly_income_uzs=income,
        liveness_passed=liveness_passed,
    )

    # Inspect customer's live active & overdue installment contracts inside ZARVON
    z_state = _inspect_zarvon_credit_state(user)
    zarvon_monthly = z_state["monthly_uzs"]

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
        reasons.append(f"MIB_DEBT_BLOCKED: Majburiy ijro byurosida {bureau['mib_debt_uzs']:,} so‘m qarzdorlik aniqlandi — faqat naqd savdo.")
    elif bureau["mib_status"] == "WARNING":
        decision = "MANUAL_REVIEW"
        reasons.append(f"MIB_WARNING: MIBda {bureau['mib_debt_uzs']:,} so‘m jarima mavjud.")
    else:
        reasons.append("MIB_CLEAN: Majburiy ijro byurosida qarzdorlik topilmadi.")

    if bureau["external_overdue_days_max"] > 0 or z_state["overdue_count"] > 0:
        od_days = max(bureau["external_overdue_days_max"], z_state["overdue_max_days"])
        decision = "DECLINE"
        recommended_limit = 0
        reasons.append(
            f"OVERDUE_CASH_ONLY: Kechikkan kredit/to‘lov ({od_days} kun) aniqlandi — muddatli to‘lov yopilgan, faqat naqd savdo qila oladi."
        )
    elif external_obligations or z_state["active_count"] > 0:
        tot_cnt = len(external_obligations) + z_state["active_count"]
        decision = "DECLINE"
        recommended_limit = 0
        reasons.append(
            f"ACTIVE_CREDIT_CASH_ONLY: Jami {tot_cnt} ta faol kredit/nasiya (oylik {existing_monthly_burden:,} so‘m, "
            f"{bureau['external_credit_history_grade']} reyting) mavjud — faqat naqd savdo ruxsat etiladi."
        )
    else:
        reasons.append("NO_ACTIVE_CREDIT_CLEAN: KATM va platforma bo‘yicha faol kredit hamda kechikish topilmadi.")

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

    if bureau.get("bureau_error"):
        decision = "MANUAL_REVIEW"
        recommended_limit = 0
        reasons.append("BUREAU_HTTP_ERROR: Tashqi byuro (KATM/MIB) javob bermadi — Nazoratchi qo‘lda tekshiradi.")

    provider_mode = "LIVE_ADAPTER" if (bureau.get("live_used") or (settings.KATM_API_URL and settings.MIB_API_URL)) else "SANDBOX_ADAPTER"
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
        bureau_trace=bureau.get("bureau_trace") or [],
        is_demo=(provider_mode == "SANDBOX_ADAPTER"),
    )
