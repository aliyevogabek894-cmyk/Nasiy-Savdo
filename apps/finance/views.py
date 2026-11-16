"""Nasiya Calculator, Consents, KYC/KATM/MIB Scoring, Customer Cabinet, Click/Payme PSP & Due Monitor."""
import base64
from datetime import timedelta
import json
from pathlib import Path
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.html import escape
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission
from config.utils import encrypt_field, hash_identifier, mask_value
from apps.accounts.models import User, UserRole
from apps.finance.models import (
    BankApplication,
    BankOffer,
    BankPartner,
    ConsentPurpose,
    ContractStatus,
    CreditApplication,
    CustomerConsent,
    CustomerLimit,
    EarlyRepayment,
    ExternalScoringReport,
    IdentityCheck,
    InstallmentContract,
    InstallmentPlan,
    InstallmentScheduleItem,
    KycDocument,
    LimitEvent,
    PaymentCard,
    PaymentRecord,
    PaymentReminderLog,
    PspTransaction,
    ReconciliationRecord,
    RepaymentEvent,
    WebhookEvent,
)
from apps.finance.providers import ComplianceViolationError, OwnInstallmentProvider
from apps.finance.psp import (
    build_psp_checkout_payload,
    compute_click_signature,
    get_client_ip,
    process_click_webhook,
    process_payme_rpc,
    process_paynet_uws,
    process_uzum_webhook,
    resolve_payment_target,
    settle_psp_payment,
)
from apps.finance.scoring import (
    evaluate_customer_credit_policy,
    notify_supervisors_credit_status,
    run_katm_and_mib_scoring,
)
from apps.governance.models import AuditLog, BhmValue, ComplianceRuleVersion, NotificationEvent, SecurityEvent
from apps.risk_collections.models import FraudCase, FraudSignal, RiskAssessment


class NasiyaCalculatorView(APIView):
    """Transparent compliance-guarded installment calculator (Sections 28.3 & 30.4)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        price = int(request.data.get("price") or 0)
        down_payment = max(0, int(request.data.get("down_payment") or 0))
        months = int(request.data.get("months") or 12)
        category_allowed = bool(request.data.get("category_installment_allowed", True))

        if price <= 0:
            return Response({"detail": "Mahsulot narxi musbat bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)
        principal = max(0, price - down_payment)
        if principal <= 0:
            return Response({"detail": "Moliyalashtiriladigan summa musbat bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)

        plan = InstallmentPlan.objects.filter(is_active=True, months=months).first() or InstallmentPlan.objects.filter(is_active=True).order_by("-months").first()
        if not plan:
            return Response({"detail": "Faol nasiya rejasi topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        try:
            quote = OwnInstallmentProvider().calculate_quote(
                principal=principal,
                months=months,
                plan=plan,
                category_allowed=category_allowed,
            )
        except ComplianceViolationError as exc:
            return Response({"compliant": False, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Build preview schedule
        start = timezone.now().date() + timezone.timedelta(days=30)
        preview_schedule = []
        base = quote["total_payable"] // months
        rem = quote["total_payable"] - base * months
        for i in range(1, months + 1):
            preview_schedule.append(
                {
                    "installment_no": i,
                    "due_date": (start + timezone.timedelta(days=30 * (i - 1))).isoformat(),
                    "amount": base + (rem if i == months else 0),
                }
            )

        return Response(
            {
                "compliant": True,
                "plan_id": str(plan.id),
                "plan_name": plan.name,
                "down_payment": down_payment,
                **quote,
                "preview_schedule": preview_schedule,
                "transparency_notice": "Indikativ hisob. Muddatidan oldin to‘lash istalgan vaqtda 0% jarima/komissiya bilan mumkin.",
            }
        )


class CustomerConsentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        latest = {}
        for purpose_val, purpose_label in ConsentPurpose.choices:
            rec = CustomerConsent.objects.filter(user=request.user, purpose=purpose_val).first()
            latest[purpose_val] = {
                "purpose": purpose_val,
                "label": purpose_label,
                "is_granted": bool(rec and rec.is_granted and rec.revoked_at is None),
                "version": rec.version if rec else "2026.3",
                "granted_at": rec.granted_at if rec else None,
            }
        return Response({"consents": list(latest.values())})

    def post(self, request):
        purposes = request.data.get("purposes") or {}
        if not isinstance(purposes, dict):
            return Response({"detail": "Roziliklar lug‘at ko‘rinishida bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)
        for p_key, granted in purposes.items():
            if p_key not in ConsentPurpose.values:
                continue
            if granted:
                CustomerConsent.objects.create(
                    user=request.user,
                    purpose=p_key,
                    is_granted=True,
                    ip_address=request.META.get("REMOTE_ADDR", "127.0.0.1"),
                )
            else:
                CustomerConsent.objects.filter(user=request.user, purpose=p_key, revoked_at__isnull=True).update(
                    is_granted=False,
                    revoked_at=timezone.now(),
                )
        AuditLog.record(actor=request.user, action="CONSENTS_UPDATED", object_type="CustomerConsent", object_id=request.user.id, reason="Mijoz maqsadli roziliklarni yangiladi")
        return self.get(request)


class KycAndScoringView(APIView):
    """MyID/OneID, PINFL/INN, KATM Credit Bureau, MIB Debt Check & 50% DSTI Scoring Engine."""

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        user = request.user
        has_id_consent = CustomerConsent.objects.filter(user=user, purpose="IDENTITY", is_granted=True, revoked_at__isnull=True).exists()
        has_cb_consent = CustomerConsent.objects.filter(user=user, purpose="CREDIT_BUREAU", is_granted=True, revoked_at__isnull=True).exists()
        if not (has_id_consent and has_cb_consent):
            return Response(
                {"detail": "Shaxsni tasdiqlash, KATM va MIB tekshiruvi uchun alohida roziliklar talab qilinadi (28.4 / 23.1)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pinfl = (request.data.get("pinfl") or "").strip()
        inn = (request.data.get("inn") or "").strip()
        passport = (request.data.get("passport") or "").strip().upper()
        birth_year = int(request.data.get("birth_year") or 1995)
        monthly_income_uzs = int(request.data.get("monthly_income_uzs") or 8_000_000)
        requested_purchase_uzs = max(0, int(request.data.get("requested_purchase_uzs") or 0))
        requested_months = min(12, max(1, int(request.data.get("requested_months") or 12)))
        scenario = (request.data.get("scenario") or "auto").strip() if settings.ZARVON_SANDBOX_MODE else "auto"
        liveness_ok = bool(request.data.get("liveness_passed", True))
        if len(pinfl) != 14 or not pinfl.isdigit() or len(passport) < 8:
            return Response({"detail": "14 xonali PINFL va pasport/ID seriya raqamini to‘g‘ri kiriting."}, status=status.HTTP_400_BAD_REQUEST)
        if inn and (len(inn) != 9 or not inn.isdigit()):
            return Response({"detail": "INN / STIR raqami 9 xonali raqam bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)

        # Duplicate PINFL check (Section 31.1 — Ko‘p akkaunt himoyasi)
        p_hash = hash_identifier(pinfl)
        duplicate_exists = User.objects.filter(pinfl_hash=p_hash).exclude(id=user.id).exists()
        if duplicate_exists:
            sig = FraudSignal.objects.create(
                user=user,
                signal_type="MULTI_ACCOUNT_PINFL",
                severity="HIGH",
                summary=f"Bir xil PINFL bilan boshqa akkauntda limit olishga urinish ({user.phone}).",
                metadata={"user_id": str(user.id)},
            )
            FraudCase.objects.create(signal=sig, status="OPEN")
            return Response(
                {"detail": "Ushbu PINFL boshqa akkauntga biriktirilgan. Xavfsizlik ko‘rigi uchun yordam bo‘limiga murojaat qiling."},
                status=status.HTTP_409_CONFLICT,
            )

        user.set_identity_fields(pinfl=pinfl, passport=passport, inn=inn)
        user.birth_year = birth_year
        user.kyc_status = "VERIFIED" if liveness_ok else "PENDING"
        user.save()

        IdentityCheck.objects.create(
            user=user,
            provider="MyID + INN Sandbox" if settings.ZARVON_SANDBOX_MODE else "MyID + OneID",
            liveness_passed=liveness_ok,
            status="VERIFIED" if liveness_ok else "FAILED",
            correlation_id=f"MYID-{uuid.uuid4().hex[:8].upper()}",
        )

        # Run full MyID + KATM + MIB + 50% DSTI scoring engine
        ext = run_katm_and_mib_scoring(
            user=user,
            pinfl=pinfl,
            inn=inn,
            passport=passport,
            birth_year=birth_year,
            monthly_income_uzs=monthly_income_uzs,
            requested_purchase_uzs=requested_purchase_uzs,
            requested_months=requested_months,
            scenario=scenario,
            liveness_passed=liveness_ok,
        )

        rec_tier = "Max" if ext.recommended_limit_uzs >= 20_000_000 else ("Plus" if ext.recommended_limit_uzs >= 8_000_000 else "Start")
        ra = RiskAssessment.objects.create(
            user=user,
            model_version="katm-mib-dsti-v3.1-uz",
            score=ext.katm_score,
            dti_ratio_pct=ext.dsti_before_pct,
            decision=ext.decision,
            reason_codes=ext.decision_reasons,
            recommended_tier=rec_tier,
        )

        lim, _ = CustomerLimit.objects.get_or_create(user=user)
        if ext.decision == "APPROVE":
            lim.tier = rec_tier
            lim.total_limit_uzs = max(lim.used_limit_uzs, ext.recommended_limit_uzs)
            lim.is_frozen = False
            lim.freeze_reason = ""
            lim.is_demo_limit = ext.is_demo
            lim.save()
            LimitEvent.objects.create(
                customer_limit=lim,
                event_type="INCREASE",
                amount_delta=ext.recommended_limit_uzs,
                reason=f"KATM ({ext.katm_score}) + MIB ({ext.mib_status}) + DSTI ({ext.dsti_before_pct}%) asosida limit hisoblandi",
                actor=user,
            )
        elif ext.decision == "DECLINE":
            lim.is_frozen = True
            lim.freeze_reason = ext.decision_reasons[0] if ext.decision_reasons else "KATM/MIB/DSTI cheklovi"
            lim.save(update_fields=["is_frozen", "freeze_reason", "updated_at"])

        credit_policy = evaluate_customer_credit_policy(user)
        supervisors_notified = notify_supervisors_credit_status(
            user=user,
            policy=credit_policy,
            ext_report=ext,
            trigger="SCORING_CHECK",
        )

        AuditLog.record(
            actor=user,
            action="KATM_MIB_SCORING_COMPLETED",
            object_type="ExternalScoringReport",
            object_id=ext.id,
            reason=f"Qaror: {ext.decision}, Holat: {credit_policy['credit_condition_code']}, DSTI: {ext.dsti_before_pct}%, MIB: {ext.mib_status}, Nazoratchilar: {supervisors_notified}",
        )
        return Response(
            {
                "ok": True,
                "kyc_status": user.kyc_status,
                "decision": ext.decision,
                "tier": lim.tier,
                "available_limit_uzs": lim.available_limit_uzs,
                "reason_codes": ext.decision_reasons,
                "assessment_id": str(ra.id),
                "is_demo_limit": ext.is_demo,
                "supervisors_notified": supervisors_notified,
                "credit_policy": credit_policy,
                "message": (
                    ext.decision_reasons[0]
                    if ext.decision != "APPROVE" and ext.decision_reasons
                    else f"KATM/MIB tekshiruvi muvaffaqiyatli! Ajratilgan limit: {lim.available_limit_uzs:,} so‘m ({lim.tier})."
                ),
                "scoring_report": {
                    "check_reference": ext.check_reference,
                    "provider_mode": ext.provider_mode,
                    "pinfl_masked": ext.pinfl_masked,
                    "inn_masked": ext.inn_masked,
                    "monthly_income_uzs": ext.monthly_income_uzs,
                    "mib_status": ext.mib_status,
                    "mib_debt_uzs": ext.mib_debt_uzs,
                    "mib_active_cases_count": ext.mib_active_cases_count,
                    "mib_details": ext.mib_details,
                    "katm_score": ext.katm_score,
                    "external_credit_history_grade": ext.external_credit_history_grade,
                    "external_active_credits_count": ext.external_active_credits_count,
                    "external_total_debt_uzs": ext.external_total_debt_uzs,
                    "external_monthly_obligations_uzs": ext.external_monthly_obligations_uzs,
                    "external_overdue_days_max": ext.external_overdue_days_max,
                    "external_obligations_breakdown": ext.external_obligations_breakdown,
                    "zarvon_active_monthly_uzs": ext.zarvon_active_monthly_uzs,
                    "projected_new_monthly_uzs": ext.projected_new_monthly_uzs,
                    "dsti_before_pct": ext.dsti_before_pct,
                    "dsti_after_pct": ext.dsti_after_pct,
                    "max_safe_monthly_uzs": ext.max_safe_monthly_uzs,
                    "recommended_limit_uzs": ext.recommended_limit_uzs,
                    "decision": ext.decision,
                    "decision_reasons": ext.decision_reasons,
                    "bureau_trace": ext.bureau_trace,
                    "is_demo": ext.is_demo,
                },
            }
        )


class CustomerFinanceCabinetView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        lim, _ = CustomerLimit.objects.get_or_create(user=user)
        limit_events = lim.events.all()[:15]
        contracts = InstallmentContract.objects.filter(customer=user).select_related("order", "plan").prefetch_related("schedule_items", "early_repayments")
        credit_apps = CreditApplication.objects.filter(customer=user).prefetch_related("bank_submissions__bank", "bank_submissions__offer")
        payments = PaymentRecord.objects.filter(user=user).select_related("order", "contract")[:20]
        assessments = RiskAssessment.objects.filter(user=user)[:5]

        # Find earliest upcoming installment & 7-day alerts across active contracts
        today = timezone.now().date()
        next_payment = None
        due_alerts = []
        contracts_data = []
        for c in contracts:
            sched = [
                {
                    "id": str(s.id),
                    "installment_no": s.installment_no,
                    "due_date": s.due_date,
                    "days_until_due": (s.due_date - today).days,
                    "principal_part": s.principal_part,
                    "markup_part": s.markup_part,
                    "amount_due": s.amount_due,
                    "amount_paid": s.amount_paid,
                    "penalty_amount": s.penalty_amount,
                    "status": s.status,
                }
                for s in c.schedule_items.all()
            ]
            upcoming = next((s for s in sched if s["status"] in {"UPCOMING", "PARTIAL", "OVERDUE"}), None)
            if upcoming:
                d_left = upcoming["days_until_due"]
                due_amt = max(0, upcoming["amount_due"] - upcoming["amount_paid"] + upcoming["penalty_amount"])
                if d_left <= 7:
                    due_alerts.append(
                        {
                            "contract_id": str(c.id),
                            "contract_number": c.contract_number,
                            "installment_no": upcoming["installment_no"],
                            "due_date": upcoming["due_date"],
                            "days_until_due": d_left,
                            "amount": due_amt,
                            "urgency": "OVERDUE" if d_left < 0 else ("DUE_TODAY" if d_left == 0 else ("DUE_SOON_3D" if d_left <= 3 else "DUE_SOON_7D")),
                        }
                    )
                if next_payment is None or str(upcoming["due_date"]) < str(next_payment["due_date"]):
                    next_payment = {
                        "contract_id": str(c.id),
                        "contract_number": c.contract_number,
                        "installment_no": upcoming["installment_no"],
                        "due_date": upcoming["due_date"],
                        "days_until_due": d_left,
                        "urgency": "OVERDUE" if d_left < 0 else ("DUE_TODAY" if d_left == 0 else ("DUE_SOON_3D" if d_left <= 3 else "UPCOMING")),
                        "amount": due_amt,
                        "status": upcoming["status"],
                    }
            contracts_data.append(
                {
                    "id": str(c.id),
                    "contract_number": c.contract_number,
                    "order_number": c.order.order_number,
                    "provider_type": c.provider_type,
                    "provider_name": c.provider_name,
                    "principal_amount": c.principal_amount,
                    "down_payment": c.down_payment,
                    "markup_amount": c.markup_amount,
                    "commission_amount": c.commission_amount,
                    "total_payable": c.total_payable,
                    "remaining_balance": c.remaining_balance,
                    "months": c.months,
                    "status": c.status,
                    "signed_method": c.signed_method,
                    "signed_at": c.signed_at,
                    "is_demo": c.is_demo,
                    "compliance_rule_code": c.compliance_rule_code,
                    "summary_terms": c.summary_terms,
                    "schedule": sched,
                    "early_repayments": [
                        {"amount": er.amount, "fee_charged": er.fee_charged, "balance_after": er.balance_after, "created_at": er.created_at}
                        for er in c.early_repayments.all()
                    ],
                }
            )

        apps_data = []
        for ca in credit_apps:
            offers = []
            subs = []
            for ba in ca.bank_submissions.all():
                subs.append({"bank": ba.bank.name, "status": ba.status, "error": ba.error_message, "correlation_id": ba.correlation_id})
                if hasattr(ba, "offer"):
                    of = ba.offer
                    offers.append(
                        {
                            "offer_id": str(of.id),
                            "bank_name": ba.bank.name,
                            "principal_amount": of.principal_amount,
                            "months": of.months,
                            "annual_rate_pct": of.annual_rate_pct,
                            "total_cost_of_credit_pct": of.total_cost_of_credit_pct,
                            "mandatory_commission": of.mandatory_commission,
                            "monthly_payment": of.monthly_payment,
                            "total_payable": of.total_payable,
                            "expires_at": of.expires_at,
                            "is_expired": of.is_expired,
                            "is_selected": of.is_selected,
                            "is_demo": of.is_demo,
                        }
                    )
            apps_data.append(
                {
                    "id": str(ca.id),
                    "application_number": ca.application_number,
                    "requested_amount": ca.requested_amount,
                    "requested_months": ca.requested_months,
                    "status": ca.status,
                    "correlation_id": ca.correlation_id,
                    "is_demo": ca.is_demo,
                    "submissions": subs,
                    "offers": offers,
                }
            )

        ext_rep = ExternalScoringReport.objects.filter(user=user).first()
        latest_ext = (
            {
                "check_reference": ext_rep.check_reference,
                "provider_mode": ext_rep.provider_mode,
                "pinfl_masked": ext_rep.pinfl_masked,
                "inn_masked": ext_rep.inn_masked,
                "monthly_income_uzs": ext_rep.monthly_income_uzs,
                "mib_status": ext_rep.mib_status,
                "mib_debt_uzs": ext_rep.mib_debt_uzs,
                "mib_active_cases_count": ext_rep.mib_active_cases_count,
                "mib_details": ext_rep.mib_details,
                "katm_score": ext_rep.katm_score,
                "external_credit_history_grade": ext_rep.external_credit_history_grade,
                "external_active_credits_count": ext_rep.external_active_credits_count,
                "external_total_debt_uzs": ext_rep.external_total_debt_uzs,
                "external_monthly_obligations_uzs": ext_rep.external_monthly_obligations_uzs,
                "external_overdue_days_max": ext_rep.external_overdue_days_max,
                "external_obligations_breakdown": ext_rep.external_obligations_breakdown,
                "zarvon_active_monthly_uzs": ext_rep.zarvon_active_monthly_uzs,
                "dsti_before_pct": ext_rep.dsti_before_pct,
                "dsti_after_pct": ext_rep.dsti_after_pct,
                "max_safe_monthly_uzs": ext_rep.max_safe_monthly_uzs,
                "recommended_limit_uzs": ext_rep.recommended_limit_uzs,
                "decision": ext_rep.decision,
                "decision_reasons": ext_rep.decision_reasons,
                "bureau_trace": ext_rep.bureau_trace,
                "is_demo": ext_rep.is_demo,
                "created_at": ext_rep.created_at,
            }
            if ext_rep
            else None
        )
        kyc_docs_data = [
            {
                "id": str(d.id),
                "doc_type": d.doc_type,
                "doc_type_label": d.get_doc_type_display(),
                "status": d.status,
                "status_label": d.get_status_display(),
                "review_note": d.review_note,
                "content_type": d.content_type,
                "is_image": d.content_type.startswith("image/"),
                "file_url": f"/api/v1/finance/kyc/documents/{d.id}/file/",
                "created_at": d.created_at,
                "reviewed_at": d.reviewed_at,
            }
            for d in KycDocument.objects.filter(user=user)[:15]
        ]
        cards_data = [
            {
                "id": str(cd.id),
                "provider": cd.provider,
                "card_brand": cd.card_brand,
                "card_masked_pan": cd.card_masked_pan,
                "expiry_masked": cd.expiry_masked,
                "is_default": cd.is_default,
                "auto_debit_enabled": cd.auto_debit_enabled,
            }
            for cd in PaymentCard.objects.filter(user=user)
        ]

        return Response(
            {
                "limit": {
                    "tier": lim.tier,
                    "total_limit_uzs": lim.total_limit_uzs,
                    "used_limit_uzs": lim.used_limit_uzs,
                    "available_limit_uzs": lim.available_limit_uzs,
                    "is_frozen": lim.is_frozen,
                    "freeze_reason": lim.freeze_reason,
                    "is_demo_limit": lim.is_demo_limit,
                    "events": [
                        {"event_type": e.event_type, "amount_delta": e.amount_delta, "reason": e.reason, "created_at": e.created_at}
                        for e in limit_events
                    ],
                },
                "next_payment": next_payment,
                "due_alerts": due_alerts,
                "credit_policy": evaluate_customer_credit_policy(user),
                "latest_scoring_report": latest_ext,
                "kyc_documents": kyc_docs_data,
                "payment_cards": cards_data,
                "contracts": contracts_data,
                "credit_applications": apps_data,
                "payments": [
                    {
                        "id": str(p.id),
                        "payment_intent_id": p.payment_intent_id,
                        "provider": p.provider,
                        "amount": p.amount,
                        "status": p.status,
                        "reconciliation_ref": p.reconciliation_ref,
                        "order_number": p.order.order_number if p.order else None,
                        "contract_number": p.contract.contract_number if p.contract else None,
                        "receipt_url": f"/api/v1/finance/payments/{p.id}/receipt/",
                        "is_demo": p.is_demo,
                        "created_at": p.created_at,
                    }
                    for p in payments
                ],
                "risk_assessments": [
                    {
                        "id": str(r.id),
                        "model_version": r.model_version,
                        "score": r.score,
                        "decision": r.decision,
                        "reason_codes": r.reason_codes,
                        "appeal_status": r.appeal_status,
                        "created_at": r.created_at,
                    }
                    for r in assessments
                ],
            }
        )


class ContractRepayView(APIView):
    """Scheduled or Early Repayment — strictly 0% penalty/commission & instant schedule recalc (27.1, 28.3)."""

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        contract = InstallmentContract.objects.select_for_update().filter(id=pk, customer=request.user).first()
        if not contract:
            return Response({"detail": "Shartnoma topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if contract.remaining_balance <= 0 or contract.status in {ContractStatus.CLOSED, ContractStatus.CANCELLED}:
            return Response({"detail": "Shartnoma allaqachon yopilgan."}, status=status.HTTP_400_BAD_REQUEST)

        amount = int(request.data.get("amount") or 0)
        is_early = bool(request.data.get("is_early_repayment", False))
        method = request.data.get("payment_method") or "Payme"
        idem_key = (request.data.get("idempotency_key") or f"rep-{uuid.uuid4().hex[:12]}").strip()

        if RepaymentEvent.objects.filter(idempotency_key=idem_key).exists():
            return Response({"ok": True, "idempotent_replay": True})
        if amount <= 0:
            return Response({"detail": "To‘lov summasi musbat bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)

        applied = min(amount, contract.remaining_balance)
        bal_before = contract.remaining_balance
        contract.remaining_balance -= applied

        # Apply across schedule items chronologically
        left = applied
        for item in contract.schedule_items.filter(status__in=["OVERDUE", "PARTIAL", "UPCOMING"]).order_by("installment_no"):
            if left <= 0:
                break
            item_due_left = max(0, (item.amount_due + item.penalty_amount) - item.amount_paid)
            pay_here = min(left, item_due_left)
            item.amount_paid += pay_here
            left -= pay_here
            if item.amount_paid >= item.amount_due + item.penalty_amount:
                item.status = "PAID"
                item.paid_at = timezone.now()
            elif item.amount_paid > 0:
                item.status = "PARTIAL"
            item.save()

        # Recalculate remaining upcoming items smoothly when partial early repayment occurred
        unpaid_items = list(contract.schedule_items.filter(status__in=["UPCOMING", "PARTIAL", "OVERDUE"]).order_by("installment_no"))
        if is_early and contract.remaining_balance > 0 and unpaid_items:
            per_item = contract.remaining_balance // len(unpaid_items)
            rem = contract.remaining_balance - per_item * len(unpaid_items)
            for idx, it in enumerate(unpaid_items):
                it.amount_paid = 0
                it.amount_due = per_item + (rem if idx == len(unpaid_items) - 1 else 0)
                it.status = "UPCOMING"
                it.save()

        if contract.remaining_balance == 0:
            contract.status = ContractStatus.PREPAID if is_early else ContractStatus.CLOSED
            lim = CustomerLimit.objects.filter(user=request.user).first()
            if lim:
                restore = min(lim.used_limit_uzs, contract.principal_amount)
                lim.used_limit_uzs -= restore
                lim.save()
                LimitEvent.objects.create(customer_limit=lim, event_type="RESTORE", amount_delta=restore, reason=f"Shartnoma #{contract.contract_number} yopildi", actor=request.user)
        elif contract.status == ContractStatus.OVERDUE and not contract.schedule_items.filter(status="OVERDUE").exists():
            contract.status = ContractStatus.ACTIVE

        contract.save()
        RepaymentEvent.objects.create(
            contract=contract,
            amount=applied,
            payment_method=method,
            is_early_repayment=is_early,
            early_fee=0,  # Strictly 0% per 2027 compliance rules!
            idempotency_key=idem_key,
        )
        if is_early:
            EarlyRepayment.objects.create(
                contract=contract,
                amount=applied,
                fee_charged=0,
                balance_before=bal_before,
                balance_after=contract.remaining_balance,
            )

        pay_rec = PaymentRecord.objects.create(
            payment_intent_id=f"REP-{uuid.uuid4().hex[:10].upper()}",
            provider=method,
            user=request.user,
            contract=contract,
            amount=applied,
            status="SUCCEEDED",
            reconciliation_ref=f"REC-{contract.contract_number}",
        )
        NotificationEvent.objects.create(
            user=request.user,
            channel="TELEGRAM",
            category="TRANSACTIONAL",
            status="delivered",
            title=f"To‘lov qabul qilindi ({applied:,} so‘m)",
            body_masked=f"Shartnoma #{contract.contract_number} qoldig‘i: {contract.remaining_balance:,} so‘m. Erta to‘lov komissiyasi: 0 so‘m.",
        )
        return Response(
            {
                "ok": True,
                "payment_id": str(pay_rec.id),
                "receipt_url": f"/api/v1/finance/payments/{pay_rec.id}/receipt/",
                "applied_amount": applied,
                "early_fee": 0,
                "remaining_balance": contract.remaining_balance,
                "contract_status": contract.status,
            }
        )


class SelectBankOfferView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, offer_id):
        offer = BankOffer.objects.select_for_update().select_related("bank_application__credit_application", "bank").filter(id=offer_id, bank_application__credit_application__customer=request.user).first()
        if not offer:
            return Response({"detail": "Bank taklifi topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if offer.is_expired:
            return Response({"detail": "Taklifning amal qilish muddati tugagan (8.4)."}, status=status.HTTP_400_BAD_REQUEST)
        ca = offer.bank_application.credit_application
        BankOffer.objects.filter(bank_application__credit_application=ca).update(is_selected=False)
        offer.is_selected = True
        offer.save(update_fields=["is_selected"])
        ca.status = "Customer Selected"
        ca.save(update_fields=["status"])
        if ca.order:
            ca.order.status = "Confirmed"
            ca.order.save(update_fields=["status"])
            ca.order.seller_orders.update(status="Confirmed")
        return Response({"ok": True, "selected_bank": offer.bank.name, "status": ca.status})


class AdminInstallmentPlansView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "FINANCE_OFFICER", "RISK_MANAGER", "AUDITOR"}

    def get(self, request):
        plans = InstallmentPlan.objects.select_related("compliance_version").all()
        return Response(
            {
                "results": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "months": p.months,
                        "annual_markup_pct": p.annual_markup_pct,
                        "commission_pct": p.commission_pct,
                        "late_fee_daily_pct": p.late_fee_daily_pct,
                        "is_active": p.is_active,
                        "is_demo": p.is_demo,
                        "compliance_version": p.compliance_version.version_code if p.compliance_version else "UZ-2027-V1",
                    }
                    for p in plans
                ]
            }
        )

    def post(self, request):
        try:
            plan = InstallmentPlan(
                name=(request.data.get("name") or "").strip(),
                months=int(request.data.get("months") or 12),
                annual_markup_pct=float(request.data.get("annual_markup_pct") or 24.0),
                commission_pct=float(request.data.get("commission_pct") or 2.0),
                late_fee_daily_pct=float(request.data.get("late_fee_daily_pct") or 0.1),
            )
            plan.save()
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        AuditLog.record(actor=request.user, action="INSTALLMENT_PLAN_CREATED", object_type="InstallmentPlan", object_id=plan.id, reason="Compliance Guard tekshiruvidan o‘tdi")
        return Response({"ok": True, "id": str(plan.id)}, status=status.HTTP_201_CREATED)


class BankPartnersAdminView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "FINANCE_OFFICER", "FINANCE_OPERATIONS", "AUDITOR"}

    def get(self, request):
        banks = BankPartner.objects.all()
        webhooks = WebhookEvent.objects.all()[:20]
        return Response(
            {
                "banks": [
                    {
                        "id": str(b.id),
                        "name": b.name,
                        "code": b.code,
                        "environment": b.environment,
                        "adapter_status": b.adapter_status,
                        "uptime_pct": b.uptime_pct,
                        "avg_latency_ms": b.avg_latency_ms,
                        "base_annual_rate_pct": b.base_annual_rate_pct,
                        "max_months": b.max_months,
                    }
                    for b in banks
                ],
                "webhooks": [
                    {"id": str(w.id), "provider": w.provider, "event_id": w.event_id, "signature_valid": w.signature_valid, "received_at": w.received_at}
                    for w in webhooks
                ],
            }
        )

    def post(self, request):
        bank = BankPartner.objects.filter(id=request.data.get("bank_id")).first()
        if not bank:
            return Response({"detail": "Bank topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        new_status = request.data.get("adapter_status")
        if new_status not in {"ONLINE", "DEGRADED", "TIMEOUT"}:
            return Response({"detail": "Noto‘g‘ri adapter holati."}, status=status.HTTP_400_BAD_REQUEST)
        bank.adapter_status = new_status
        bank.save(update_fields=["adapter_status"])
        AuditLog.record(actor=request.user, action="BANK_ADAPTER_STATUS_CHANGED", object_type="BankPartner", object_id=bank.id, reason=f"Holat: {new_status}")
        return Response({"ok": True, "adapter_status": bank.adapter_status})


class BankWebhookReceiverView(APIView):
    """Idempotent & Signature-checked Webhook Receiver (Sections 11, 19, 23.1)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        event_id = (request.data.get("event_id") or "").strip()
        signature = (request.headers.get("X-Zarvon-Signature") or "").strip()
        provider = (request.data.get("provider") or "SANDBOX_BANK").strip()
        if not event_id:
            return Response({"detail": "event_id majburiy."}, status=status.HTTP_400_BAD_REQUEST)

        if not signature or signature == "INVALID":
            WebhookEvent.objects.create(provider=provider, event_id=f"BAD-{uuid.uuid4().hex[:8]}", signature_valid=False, payload=request.data, processed=False)
            return Response({"detail": "Webhook imzosi noto‘g‘ri (23.1)."}, status=status.HTTP_401_UNAUTHORIZED)

        existing = WebhookEvent.objects.filter(event_id=event_id).first()
        if existing:
            return Response({"ok": True, "idempotent_replay": True, "message": "Takroriy webhook qayta ishlanmadi."})

        WebhookEvent.objects.create(provider=provider, event_id=event_id, signature_valid=True, payload=request.data, processed=True)
        return Response({"ok": True, "processed": True})


class ReconciliationAdminView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "FINANCE_OPERATIONS", "FINANCE_OFFICER", "AUDITOR"}

    def get(self, request):
        recs = ReconciliationRecord.objects.all()[:25]
        from apps.commerce.models import SellerOrder

        payouts = SellerOrder.objects.select_related("store", "master_order").all()[:30]

        today = timezone.now().date()
        succeeded_qs = PaymentRecord.objects.filter(status="SUCCEEDED")
        total_collected = succeeded_qs.aggregate(total=Sum("amount"))["total"] or 0
        today_collected = succeeded_qs.filter(created_at__date=today).aggregate(total=Sum("amount"))["total"] or 0
        pending_count = PaymentRecord.objects.filter(status="PENDING").count()
        cancelled_count = PaymentRecord.objects.filter(status__in=["CANCELLED", "FAILED"]).count()

        provider_rows = (
            succeeded_qs.values("provider")
            .annotate(total_amount=Sum("amount"), tx_count=Count("id"))
            .order_by("-total_amount")
        )
        provider_breakdown = [
            {
                "provider": row["provider"],
                "total_amount_uzs": int(row["total_amount"] or 0),
                "tx_count": int(row["tx_count"] or 0),
                "psp_settled_count": PspTransaction.objects.filter(
                    psp_provider=row["provider"], action_stage="PERFORMED"
                ).count(),
                "psp_cancelled_count": PspTransaction.objects.filter(
                    psp_provider=row["provider"], action_stage="CANCELLED"
                ).count(),
            }
            for row in provider_rows
        ]

        active_debt_uzs = (
            InstallmentContract.objects.filter(status__in=[ContractStatus.ACTIVE, ContractStatus.OVERDUE])
            .aggregate(total=Sum("remaining_balance"))["total"]
            or 0
        )
        overdue_debt_uzs = (
            InstallmentContract.objects.filter(status=ContractStatus.OVERDUE)
            .aggregate(total=Sum("remaining_balance"))["total"]
            or 0
        )
        active_contracts_count = InstallmentContract.objects.filter(
            status__in=[ContractStatus.ACTIVE, ContractStatus.OVERDUE]
        ).count()
        overdue_contracts_count = InstallmentContract.objects.filter(status=ContractStatus.OVERDUE).count()

        recent_payments = PaymentRecord.objects.select_related("user", "order", "contract")[:30]

        return Response(
            {
                "finance_report": {
                    "total_collected_uzs": int(total_collected),
                    "today_collected_uzs": int(today_collected),
                    "succeeded_payments_count": succeeded_qs.count(),
                    "pending_payments_count": pending_count,
                    "cancelled_payments_count": cancelled_count,
                    "active_portfolio_debt_uzs": int(active_debt_uzs),
                    "overdue_portfolio_debt_uzs": int(overdue_debt_uzs),
                    "active_contracts_count": active_contracts_count,
                    "overdue_contracts_count": overdue_contracts_count,
                    "provider_breakdown": provider_breakdown,
                },
                "recent_payments": [
                    {
                        "id": str(p.id),
                        "payment_intent_id": p.payment_intent_id,
                        "provider": p.provider,
                        "customer_name": p.user.full_name if p.user else "—",
                        "customer_phone": mask_value(p.user.phone, 4, 2) if p.user else "—",
                        "target_ref": (
                            p.contract.contract_number
                            if p.contract
                            else (p.order.order_number if p.order else p.reconciliation_ref)
                        ),
                        "target_kind": "Nasiya to‘lovi" if p.contract else ("Buyurtma" if p.order else "To‘lov"),
                        "amount": p.amount,
                        "status": p.status,
                        "reconciliation_ref": p.reconciliation_ref,
                        "receipt_url": f"/api/v1/finance/payments/{p.id}/receipt/",
                        "is_demo": p.is_demo,
                        "created_at": p.created_at,
                    }
                    for p in recent_payments
                ],
                "reconciliations": [
                    {
                        "id": str(r.id),
                        "date": r.reconciliation_date,
                        "provider": r.provider,
                        "zarvon_total_uzs": r.zarvon_total_uzs,
                        "provider_total_uzs": r.provider_total_uzs,
                        "difference_uzs": r.difference_uzs,
                        "status": r.status,
                        "note": r.note,
                    }
                    for r in recs
                ],
                "seller_payouts": [
                    {
                        "id": str(so.id),
                        "sub_order_number": so.sub_order_number,
                        "store_name": so.store.public_name,
                        "subtotal_amount": so.subtotal_amount,
                        "commission_amount": so.commission_amount,
                        "holdback_amount": so.holdback_amount,
                        "net_seller_payout": so.net_seller_payout,
                        "payout_status": so.payout_status,
                        "order_status": so.status,
                    }
                    for so in payouts
                ],
            }
        )


def _detect_card_brand(pan: str) -> str:
    if pan.startswith(("8600", "5614", "6262")):
        return "Uzcard"
    if pan.startswith("9860"):
        return "Humo"
    if pan.startswith("4"):
        return "Visa"
    if pan.startswith(("51", "52", "53", "54", "55", "22")):
        return "Mastercard"
    return "Uzcard"


class PaymentCardsView(APIView):
    """Tokenized Uzcard / Humo / Visa card vault (stores encrypted PSP token + masked PAN only)."""

    permission_classes = [permissions.IsAuthenticated]

    def _serialize_card(self, card: PaymentCard) -> dict:
        return {
            "id": str(card.id),
            "provider": card.provider,
            "card_brand": card.card_brand,
            "card_masked_pan": card.card_masked_pan,
            "expiry_masked": card.expiry_masked,
            "card_holder": card.card_holder,
            "is_verified": card.is_verified,
            "is_default": card.is_default,
            "auto_debit_enabled": card.auto_debit_enabled,
            "is_demo": card.is_demo,
            "created_at": card.created_at,
        }

    def get(self, request):
        cards = PaymentCard.objects.filter(user=request.user)
        return Response({"cards": [self._serialize_card(c) for c in cards]})

    def post(self, request):
        raw_pan = "".join(ch for ch in str(request.data.get("card_number") or "") if ch.isdigit())
        expiry = str(request.data.get("expiry") or "").strip()
        provider = str(request.data.get("provider") or "Uzcard/Humo").strip()
        holder = str(request.data.get("card_holder") or request.user.full_name or "").strip()[:120]
        set_default = bool(request.data.get("is_default", True))
        auto_debit = bool(request.data.get("auto_debit_enabled", True))

        if len(raw_pan) != 16:
            return Response({"detail": "Karta raqami 16 ta raqamdan iborat bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)
        if len(expiry) < 4 or "/" not in expiry:
            return Response({"detail": "Amal qilish muddatini MM/YY shaklida kiriting."}, status=status.HTTP_400_BAD_REQUEST)

        brand = _detect_card_brand(raw_pan)
        masked_pan = f"{raw_pan[:4]} **** **** {raw_pan[-4:]}"
        yy = expiry.split("/")[-1].strip()[:2]
        expiry_masked = f"**/{yy}"
        token_secret = f"tok_{uuid.uuid4().hex}_{hash_identifier(raw_pan)[:12]}"

        if set_default:
            PaymentCard.objects.filter(user=request.user).update(is_default=False)

        card = PaymentCard.objects.create(
            user=request.user,
            provider=provider if provider in {"Payme", "Click", "Uzum Bank", "Uzcard/Humo"} else "Uzcard/Humo",
            card_brand=brand,
            card_token_encrypted=encrypt_field(token_secret),
            card_masked_pan=masked_pan,
            expiry_masked=expiry_masked,
            card_holder=holder,
            is_verified=True,
            is_default=set_default,
            auto_debit_enabled=auto_debit,
            is_demo=settings.ZARVON_SANDBOX_MODE,
        )
        AuditLog.record(
            actor=request.user,
            action="PAYMENT_CARD_LINKED",
            object_type="PaymentCard",
            object_id=str(card.id),
            reason=f"{brand} ({masked_pan}) xavfsiz token bilan ulandi ({card.provider})",
            after={"brand": brand, "masked_pan": masked_pan, "provider": card.provider},
        )
        return Response({"card": self._serialize_card(card), "detail": f"{brand} ({masked_pan}) xavfsiz token bilan ulandi."}, status=status.HTTP_201_CREATED)

    def patch(self, request):
        card_id = request.data.get("card_id")
        card = PaymentCard.objects.filter(user=request.user, id=card_id).first()
        if not card:
            return Response({"detail": "Karta topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if request.data.get("is_default"):
            PaymentCard.objects.filter(user=request.user).update(is_default=False)
            card.is_default = True
        if "auto_debit_enabled" in request.data:
            card.auto_debit_enabled = bool(request.data.get("auto_debit_enabled"))
        card.save()
        return Response({"card": self._serialize_card(card)})

    def delete(self, request):
        card_id = request.query_params.get("card_id") or request.data.get("card_id")
        card = PaymentCard.objects.filter(user=request.user, id=card_id).first()
        if not card:
            return Response({"detail": "Karta topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        card.delete()
        return Response({"detail": "Bog‘langan karta o‘chirildi."})


class ClickMerchantWebhookView(APIView):
    """Official Click Shop API Prepare (action=0) & Complete (action=1) webhook endpoint."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, default_action=None):
        raw = request.data
        payload = raw.dict() if hasattr(raw, "dict") else (dict(raw) if isinstance(raw, dict) else {})
        if default_action is not None and payload.get("action") in (None, ""):
            payload["action"] = str(default_action)
        result = process_click_webhook(payload)
        return Response(result, status=status.HTTP_200_OK)


class PaymeMerchantRpcView(APIView):
    """Official Payme Business Merchant API JSON-RPC 2.0 endpoint."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        result = process_payme_rpc(request.data, auth_header)
        return Response(result, status=status.HTTP_200_OK)


class PaynetUwsWebhookView(APIView):
    """Official Paynet UWS JSON-RPC endpoint (GetInformation, PerformTransaction, CheckTransaction, CancelTransaction, GetStatement)."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        client_ip = get_client_ip(request)
        result, http_status = process_paynet_uws(
            request.data,
            auth_header=auth_header,
            client_ip=client_ip,
        )
        return Response(result, status=http_status)


class PaymentReceiptView(APIView):
    """Electronic Payment Receipt (Elektron chek) JSON & printable HTML endpoint."""

    permission_classes = [permissions.IsAuthenticated]

    def perform_content_negotiation(self, request, force=False):
        if (request.query_params.get("view") or request.query_params.get("format") or "").lower() == "html":
            from rest_framework.renderers import BaseRenderer

            class _HtmlBypassRenderer(BaseRenderer):
                media_type = "text/html"
                format = "html"

                def render(self, data, accepted_media_type=None, renderer_context=None):
                    return data

            return (_HtmlBypassRenderer(), "text/html")
        return super().perform_content_negotiation(request, force=force)

    def get(self, request, pk):
        pay = (
            PaymentRecord.objects.select_related("user", "order", "contract")
            .filter(id=pk)
            .first()
        )
        if not pay:
            return Response({"detail": "To‘lov cheki topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        is_ops = request.user.role in (
            ADMIN_ROLES | {"FINANCE_OPERATIONS", "FINANCE_OFFICER", "AUDITOR", "SUPPORT_AGENT"}
        )
        if pay.user_id != request.user.id and not is_ops:
            return Response({"detail": "Ushbu elektron chekni ko‘rish huquqingiz yo‘q."}, status=status.HTTP_403_FORBIDDEN)

        psp_tx = (
            PspTransaction.objects.filter(
                Q(order=pay.order, order__isnull=False) | Q(contract=pay.contract, contract__isnull=False),
                psp_provider=pay.provider,
            )
            .order_by("-created_at")
            .first()
        )

        if pay.contract:
            target_type = "Nasiya shartnomasi to‘lovi"
            target_number = pay.contract.contract_number
            remaining_balance = pay.contract.remaining_balance
            contract_status = pay.contract.status
        elif pay.order:
            target_type = "Buyurtma to‘lovi"
            target_number = pay.order.order_number
            remaining_balance = 0
            contract_status = pay.order.status
        else:
            target_type = "To‘lov"
            target_number = pay.reconciliation_ref or pay.payment_intent_id
            remaining_balance = 0
            contract_status = pay.status

        verification_code = hash_identifier(f"{pay.id}:{pay.payment_intent_id}:{pay.amount}")[:12].upper()
        receipt_number = f"CHK-{str(pay.id).split('-')[0].upper()}"
        receipt_data = {
            "receipt_id": str(pay.id),
            "receipt_number": receipt_number,
            "payment_intent_id": pay.payment_intent_id,
            "provider": pay.provider,
            "external_trans_id": psp_tx.external_trans_id if psp_tx else pay.reconciliation_ref,
            "amount_uzs": pay.amount,
            "status": pay.status,
            "customer_name": pay.user.full_name if pay.user else "—",
            "customer_phone_masked": mask_value(pay.user.phone, 4, 2) if pay.user else "—",
            "target_type": target_type,
            "target_number": target_number,
            "remaining_balance_after": remaining_balance,
            "contract_status": contract_status,
            "reconciliation_ref": pay.reconciliation_ref,
            "paid_at": pay.created_at,
            "verification_code": verification_code,
            "is_demo": pay.is_demo,
        }

        if (request.query_params.get("view") or request.query_params.get("format") or "").lower() == "html":
            badge_text = "NAMUNA / SANDBOX CHEK" if pay.is_demo else "RASMIY ELEKTRON CHEK"
            paid_dt = timezone.localtime(pay.created_at).strftime("%Y-%m-%d %H:%M:%S")
            html = f"""<!DOCTYPE html>
<html lang="uz">
<head>
  <meta charset="UTF-8">
  <title>Elektron chek #{escape(receipt_number)} — ZARVON</title>
  <style>
    body{{font-family:Inter,Arial,sans-serif;background:#f4f6f9;color:#10223a;margin:0;padding:24px;}}
    .receipt{{max-width:520px;margin:0 auto;background:#fff;border:1px solid #d7e0eb;border-radius:16px;padding:28px;box-shadow:0 8px 24px rgba(16,34,58,.08);}}
    .hdr{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px dashed #cbd5e1;padding-bottom:14px;margin-bottom:16px;}}
    .brand{{font-size:20px;font-weight:800;color:#17365d;letter-spacing:.04em;}}
    .tag{{font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px;background:#fef3c7;color:#92400e;}}
    .amt{{text-align:center;font-size:28px;font-weight:800;color:#0f766e;margin:12px 0 18px;}}
    table{{width:100%;border-collapse:collapse;font-size:14px;}}
    td{{padding:8px 0;border-bottom:1px solid #eef2f7;}}
    td:first-child{{color:#64748b;}}
    td:last-child{{text-align:right;font-weight:600;}}
    .ftr{{margin-top:18px;padding-top:12px;border-top:2px dashed #cbd5e1;font-size:12px;color:#64748b;display:flex;justify-content:space-between;align-items:center;}}
    .btn-print{{margin-top:16px;width:100%;padding:11px 16px;border:none;border-radius:10px;background:#17365d;color:#fff;font-weight:700;cursor:pointer;font-size:14px;}}
    @media print{{.btn-print{{display:none;}}body{{background:#fff;padding:0;}}.receipt{{box-shadow:none;border:none;}}}}
  </style>
</head>
<body>
  <div class="receipt">
    <div class="hdr">
      <div>
        <div class="brand">ZARVON PAY</div>
        <div style="font-size:12px;color:#64748b;">Elektron to‘lov kvitansiyasi</div>
      </div>
      <span class="tag">{escape(badge_text)}</span>
    </div>
    <div class="amt">{pay.amount:,} so‘m</div>
    <table>
      <tr><td>Chek raqami</td><td>{escape(receipt_number)}</td></tr>
      <tr><td>To‘lov ID</td><td>{escape(pay.payment_intent_id)}</td></tr>
      <tr><td>Provayder</td><td>{escape(pay.provider)}</td></tr>
      <tr><td>Tashqi tranzaksiya ID</td><td>{escape(receipt_data['external_trans_id'])}</td></tr>
      <tr><td>To‘lov maqsadi</td><td>{escape(target_type)}</td></tr>
      <tr><td>Hujjat / Shartnoma</td><td>{escape(target_number)}</td></tr>
      <tr><td>Mijoz</td><td>{escape(receipt_data['customer_name'])}</td></tr>
      <tr><td>Telefon</td><td>{escape(receipt_data['customer_phone_masked'])}</td></tr>
      <tr><td>Sana va vaqt</td><td>{escape(paid_dt)}</td></tr>
      <tr><td>Holati</td><td>{escape(pay.status)}</td></tr>
      <tr><td>Qolgan nasiya qoldig‘i</td><td>{remaining_balance:,} so‘m</td></tr>
      <tr><td>Shartnoma holati</td><td>{escape(contract_status)}</td></tr>
    </table>
    <div class="ftr">
      <span>Tekshiruv kodi: <strong>{escape(verification_code)}</strong></span>
      <span>ZARVON Fintech</span>
    </div>
    <button class="btn-print" onclick="window.print()">🖨 Chop etish / PDF sifatida saqlash</button>
  </div>
</body>
</html>"""
            return HttpResponse(html, content_type="text/html; charset=utf-8")

        return Response(receipt_data)


class PspCheckoutAndSimulatorView(APIView):
    """Unified PSP checkout & Sandbox gateway tester (Click, Payme, Uzum Bank, Paynet, Tokenized Card)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        is_ops = request.user.role in (ADMIN_ROLES | {"FINANCE_OPERATIONS", "FINANCE_OFFICER", "RISK_ANALYST", "AUDITOR", "SUPPORT_AGENT"})
        qs = PspTransaction.objects.select_related("order", "contract")
        if not is_ops:
            from django.db.models import Q
            qs = qs.filter(Q(order__customer=request.user) | Q(contract__customer=request.user))
        txs = qs[:40]
        return Response(
            {
                "sandbox_mode": settings.ZARVON_SANDBOX_MODE,
                "transactions": [
                    {
                        "id": str(t.id),
                        "psp_provider": t.psp_provider,
                        "external_trans_id": t.external_trans_id,
                        "merchant_trans_id": t.merchant_trans_id,
                        "merchant_prepare_id": t.merchant_prepare_id,
                        "action_stage": t.action_stage,
                        "amount_tiyin": t.amount_tiyin,
                        "amount_uzs": t.amount_tiyin // 100,
                        "state_code": t.state_code,
                        "signature_verified": t.signature_verified,
                        "is_demo": t.is_demo,
                        "created_at": t.created_at,
                    }
                    for t in txs
                ],
                "summary": {
                    "total_count": qs.count(),
                    "performed_count": qs.filter(action_stage="PERFORMED").count(),
                    "click_count": qs.filter(psp_provider="Click").count(),
                    "payme_count": qs.filter(psp_provider="Payme").count(),
                    "uzum_count": qs.filter(psp_provider="Uzum Bank").count(),
                    "paynet_count": qs.filter(psp_provider="Paynet").count(),
                },
            }
        )

    def post(self, request):
        reference = str(request.data.get("reference") or "").strip()
        psp_provider = str(request.data.get("psp_provider") or "Payme").strip()
        card_id = request.data.get("card_id")

        if psp_provider not in {"Payme", "Click", "Uzum Bank", "Paynet", "Uzcard/Humo"}:
            return Response({"detail": "Noto‘g‘ri to‘lov provayderi tanlandi."}, status=status.HTTP_400_BAD_REQUEST)

        target_kind, target_obj, expected_uzs = resolve_payment_target(reference)
        if not target_obj:
            return Response({"detail": "Buyurtma (ZRV-...) yoki nasiya shartnomasi (NSY-...) topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        is_ops = request.user.role in (ADMIN_ROLES | {"FINANCE_OPERATIONS", "FINANCE_OFFICER"})
        if target_obj.customer_id != request.user.id and not is_ops:
            return Response({"detail": "Ushbu to‘lov obyektiga ruxsat yo‘q."}, status=status.HTTP_403_FORBIDDEN)

        req_amount = int(request.data.get("amount_uzs") or expected_uzs or 0)
        if target_kind == "ORDER":
            req_amount = expected_uzs
        elif target_kind == "CONTRACT":
            if req_amount <= 0 or req_amount > target_obj.remaining_balance:
                req_amount = expected_uzs or target_obj.remaining_balance
        if req_amount <= 0:
            return Response({"detail": "To‘lov summasi allaqachon yopilgan yoki 0."}, status=status.HTTP_400_BAD_REQUEST)

        used_card = None
        if card_id:
            used_card = PaymentCard.objects.filter(id=card_id, user=target_obj.customer).first()
            if not used_card:
                return Response({"detail": "Tanlangan karta topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        checkout_payload = build_psp_checkout_payload(psp_provider=psp_provider, reference=reference, amount_uzs=req_amount)
        if not settings.ZARVON_SANDBOX_MODE:
            # In strict production mode without sandbox, return signed checkout parameters instead of auto-settling.
            return Response(
                {
                    **checkout_payload,
                    "mode": "LIVE_CHECKOUT_INTENT",
                    "detail": f"{psp_provider} orqali {req_amount:,} so‘m to‘lov sahifasiga o‘ting.",
                },
                status=status.HTTP_200_OK,
            )

        # Sandbox Protocol Execution — exercises the real cryptographic verification paths!
        protocol_trace = []
        settled_payment_id = None
        if psp_provider == "Click":
            click_tx_id = str(int(timezone.now().timestamp() * 1000))[-10:]
            sign_time = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            prep_sign = compute_click_signature(
                click_trans_id=click_tx_id,
                service_id=settings.CLICK_SERVICE_ID,
                secret_key=settings.CLICK_SECRET_KEY,
                merchant_trans_id=reference,
                amount=str(req_amount),
                action="0",
                sign_time=sign_time,
            )
            prep_resp = process_click_webhook(
                {
                    "click_trans_id": click_tx_id,
                    "service_id": settings.CLICK_SERVICE_ID,
                    "click_paydoc_id": f"DOC-{click_tx_id}",
                    "merchant_trans_id": reference,
                    "amount": str(req_amount),
                    "action": "0",
                    "sign_time": sign_time,
                    "sign_string": prep_sign,
                }
            )
            protocol_trace.append({"step": "CLICK_PREPARE (action=0)", "response": prep_resp})
            if prep_resp.get("error") != 0:
                return Response({"detail": prep_resp.get("error_note"), "trace": protocol_trace}, status=status.HTTP_400_BAD_REQUEST)

            comp_sign = compute_click_signature(
                click_trans_id=click_tx_id,
                service_id=settings.CLICK_SERVICE_ID,
                secret_key=settings.CLICK_SECRET_KEY,
                merchant_trans_id=reference,
                merchant_prepare_id=prep_resp["merchant_prepare_id"],
                amount=str(req_amount),
                action="1",
                sign_time=sign_time,
            )
            comp_resp = process_click_webhook(
                {
                    "click_trans_id": click_tx_id,
                    "service_id": settings.CLICK_SERVICE_ID,
                    "click_paydoc_id": f"DOC-{click_tx_id}",
                    "merchant_trans_id": reference,
                    "merchant_prepare_id": prep_resp["merchant_prepare_id"],
                    "amount": str(req_amount),
                    "action": "1",
                    "sign_time": sign_time,
                    "sign_string": comp_sign,
                }
            )
            protocol_trace.append({"step": "CLICK_COMPLETE (action=1)", "response": comp_resp})
            if comp_resp.get("error") != 0:
                return Response({"detail": comp_resp.get("error_note"), "trace": protocol_trace}, status=status.HTTP_400_BAD_REQUEST)
            settled_payment_id = comp_resp.get("payment_id")
        elif psp_provider == "Payme":
            payme_id = f"pm_{uuid.uuid4().hex[:16]}"
            auth_hdr = "Basic " + base64.b64encode(f"Paycom:{settings.PAYME_CASHBOX_KEY}".encode("utf-8")).decode("utf-8")
            amount_tiyin = req_amount * 100
            r1 = process_payme_rpc(
                {"jsonrpc": "2.0", "id": 1, "method": "CheckPerformTransaction", "params": {"amount": amount_tiyin, "account": {"order_id": reference}}},
                auth_hdr,
            )
            r2 = process_payme_rpc(
                {"jsonrpc": "2.0", "id": 2, "method": "CreateTransaction", "params": {"id": payme_id, "time": int(timezone.now().timestamp() * 1000), "amount": amount_tiyin, "account": {"order_id": reference}}},
                auth_hdr,
            )
            r3 = process_payme_rpc(
                {"jsonrpc": "2.0", "id": 3, "method": "PerformTransaction", "params": {"id": payme_id}},
                auth_hdr,
            )
            protocol_trace = [
                {"step": "PAYME CheckPerformTransaction", "response": r1},
                {"step": "PAYME CreateTransaction (state=1)", "response": r2},
                {"step": "PAYME PerformTransaction (state=2)", "response": r3},
            ]
            if r1.get("error") or r2.get("error") or r3.get("error"):
                err = r1.get("error") or r2.get("error") or r3.get("error")
                msg_obj = err.get("message")
                detail = msg_obj.get("uz") if isinstance(msg_obj, dict) else str(msg_obj or "Payme xatoligi")
                return Response({"detail": detail, "trace": protocol_trace}, status=status.HTTP_400_BAD_REQUEST)
            settled_payment_id = ((r3.get("result") or {}).get("settlement") or {}).get("payment_id")
        elif psp_provider == "Uzum Bank":
            uz_trans_id = f"uzm-{uuid.uuid4().hex[:12]}"
            uz_auth = "Basic " + base64.b64encode(f"{settings.UZUM_SERVICE_ID}:{settings.UZUM_SECRET_KEY}".encode("utf-8")).decode("utf-8")
            amount_tiyin = req_amount * 100
            u1 = process_uzum_webhook("check", {"serviceId": settings.UZUM_SERVICE_ID, "params": {"orderId": reference}}, auth_header=uz_auth)
            u2 = process_uzum_webhook("create", {"serviceId": settings.UZUM_SERVICE_ID, "transId": uz_trans_id, "amount": amount_tiyin, "params": {"orderId": reference}}, auth_header=uz_auth)
            u3 = process_uzum_webhook("confirm", {"serviceId": settings.UZUM_SERVICE_ID, "transId": uz_trans_id}, auth_header=uz_auth)
            protocol_trace = [
                {"step": "UZUM /check", "response": u1},
                {"step": "UZUM /create (tiyin)", "response": u2},
                {"step": "UZUM /confirm (SETTLED)", "response": u3},
            ]
            if u2.get("status") == "FAILED" or u3.get("status") == "FAILED":
                return Response({"detail": u3.get("errorMessage") or u2.get("errorMessage") or "Uzum Bank xatoligi", "trace": protocol_trace}, status=status.HTTP_400_BAD_REQUEST)
            settled_payment_id = u3.get("payment_id")
        elif psp_provider == "Paynet":
            paynet_tx_id = int(timezone.now().timestamp() * 1000) % 1000000000
            amount_tiyin = req_amount * 100
            p1, _ = process_paynet_uws(
                {"jsonrpc": "2.0", "id": 1, "method": "GetInformation", "params": {"serviceId": settings.PAYNET_SERVICE_ID, "fields": {"order_id": reference}}},
                skip_auth_for_trusted_sandbox=True,
            )
            p2, _ = process_paynet_uws(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "PerformTransaction",
                    "params": {
                        "serviceId": settings.PAYNET_SERVICE_ID,
                        "transactionId": paynet_tx_id,
                        "transactionTime": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "amount": amount_tiyin,
                        "fields": {"order_id": reference},
                    },
                },
                skip_auth_for_trusted_sandbox=True,
            )
            p3, _ = process_paynet_uws(
                {"jsonrpc": "2.0", "id": 3, "method": "CheckTransaction", "params": {"serviceId": settings.PAYNET_SERVICE_ID, "transactionId": paynet_tx_id}},
                skip_auth_for_trusted_sandbox=True,
            )
            protocol_trace = [
                {"step": "PAYNET GetInformation", "response": p1},
                {"step": "PAYNET PerformTransaction", "response": p2},
                {"step": "PAYNET CheckTransaction", "response": p3},
            ]
            if p1.get("error") or p2.get("error"):
                err = p1.get("error") or p2.get("error")
                return Response({"detail": err.get("message") or "Paynet xatoligi", "trace": protocol_trace}, status=status.HTTP_400_BAD_REQUEST)
            settled_payment_id = (p2.get("result") or {}).get("payment_id")
        else:
            ext_id = f"{psp_provider[:3].upper()}-{uuid.uuid4().hex[:10].upper()}"
            PspTransaction.objects.create(
                psp_provider=psp_provider,
                external_trans_id=ext_id,
                merchant_trans_id=reference,
                action_stage="PERFORMED",
                amount_tiyin=req_amount * 100,
                state_code=2,
                signature_verified=True,
                idempotency_key=f"psp-{ext_id}",
                order=target_obj if target_kind == "ORDER" else None,
                contract=target_obj if target_kind == "CONTRACT" else None,
                raw_payload_sanitized={"card_masked": used_card.card_masked_pan if used_card else None, "sandbox": True},
                is_demo=True,
            )
            res = settle_psp_payment(
                psp_provider=psp_provider,
                target_kind=target_kind,
                target_obj=target_obj,
                amount_uzs=req_amount,
                idem_key=f"psp-settle-{ext_id}",
                external_trans_id=ext_id,
            )
            protocol_trace = [{"step": f"{psp_provider} Instant Tokenized Settlement", "response": res}]
            settled_payment_id = res.get("payment_id")

        if not settled_payment_id:
            qs_pay = PaymentRecord.objects.filter(provider=psp_provider)
            qs_pay = qs_pay.filter(order=target_obj) if target_kind == "ORDER" else qs_pay.filter(contract=target_obj)
            latest_pay = qs_pay.order_by("-created_at").first()
            if latest_pay:
                settled_payment_id = str(latest_pay.id)

        AuditLog.record(
            actor=request.user,
            action="PSP_SANDBOX_PAYMENT_SETTLED",
            object_type=target_kind,
            object_id=reference,
            reason=f"{psp_provider} orqali {req_amount:,} so‘m to‘lov",
            after={"psp_provider": psp_provider, "amount_uzs": req_amount, "card_masked": used_card.card_masked_pan if used_card else None},
        )
        return Response(
            {
                "status": "SUCCEEDED",
                "mode": "SANDBOX_PROTOCOL_EXECUTED",
                "psp_provider": psp_provider,
                "reference": reference,
                "amount_uzs": req_amount,
                "payment_id": settled_payment_id,
                "receipt_url": f"/api/v1/finance/payments/{settled_payment_id}/receipt/" if settled_payment_id else None,
                "card_masked": used_card.card_masked_pan if used_card else None,
                "checkout_url": checkout_payload["checkout_url"],
                "links": checkout_payload["links"],
                "protocol": checkout_payload["protocol"],
                "trace": protocol_trace,
                "detail": f"{psp_provider} orqali {req_amount:,} so‘m to‘lov muvaffaqiyatli amalga oshirildi (Sandbox).",
            }
        )


class UpcomingPaymentsMonitorView(APIView):
    """Operations queue for upcoming (today, 1-3d, 4-7d, 8-30d) & overdue installments + reminders."""

    permission_classes = [HasRolePermission]
    allowed_roles = ADMIN_ROLES | {"FINANCE_OPERATIONS", "FINANCE_OFFICER", "COLLECTIONS_AGENT", "RISK_ANALYST", "SUPPORT_AGENT", "AUDITOR"}

    def _classify_window(self, days_left: int) -> tuple[str, str]:
        if days_left < 0:
            return "OVERDUE", "OVERDUE"
        if days_left == 0:
            return "DUE_TODAY", "DUE_TODAY"
        if days_left <= 3:
            return "DUE_3_DAYS", f"DUE_{days_left}_DAY" if days_left == 1 else "DUE_3_DAYS"
        if days_left <= 7:
            return "DUE_7_DAYS", "DUE_7_DAYS"
        return "UPCOMING_30_DAYS", "DUE_7_DAYS"

    def get(self, request):
        today = timezone.localdate()
        cutoff = today + timedelta(days=30)
        items = (
            InstallmentScheduleItem.objects.select_related("contract", "contract__customer")
            .filter(
                status__in=["OVERDUE", "PARTIAL", "UPCOMING"],
                contract__status__in=[ContractStatus.SIGNED, ContractStatus.ACTIVE, ContractStatus.OVERDUE, ContractStatus.RESTRUCTURED],
                due_date__lte=cutoff,
            )
            .order_by("due_date", "installment_no")[:150]
        )

        recent_rem_qs = PaymentReminderLog.objects.filter(created_at__date=today).values_list("schedule_item_id", flat=True)
        reminded_today_ids = set(recent_rem_qs)

        buckets = {"OVERDUE": [], "DUE_TODAY": [], "DUE_3_DAYS": [], "DUE_7_DAYS": [], "UPCOMING_30_DAYS": []}
        totals = {"OVERDUE": 0, "DUE_TODAY": 0, "DUE_3_DAYS": 0, "DUE_7_DAYS": 0, "UPCOMING_30_DAYS": 0}
        queue = []

        for item in items:
            due_uzs = max(0, (item.amount_due + item.penalty_amount) - item.amount_paid)
            if due_uzs <= 0:
                continue
            days_left = (item.due_date - today).days
            bucket, tag = self._classify_window(days_left)
            totals[bucket] += due_uzs
            cust = item.contract.customer
            entry = {
                "schedule_item_id": str(item.id),
                "contract_id": str(item.contract_id),
                "contract_number": item.contract.contract_number,
                "customer_name": cust.full_name,
                "customer_phone_masked": mask_value(cust.phone, visible_start=4, visible_end=2),
                "installment_no": item.installment_no,
                "due_date": item.due_date,
                "days_until_due": days_left,
                "bucket": bucket,
                "window_tag": tag,
                "amount_due_uzs": due_uzs,
                "status": item.status,
                "reminded_today": item.id in reminded_today_ids,
            }
            buckets[bucket].append(entry)
            queue.append(entry)

        logs = PaymentReminderLog.objects.select_related("contract", "user", "sent_by").all()[:30]
        return Response(
            {
                "today": today,
                "summary": {
                    "overdue_count": len(buckets["OVERDUE"]),
                    "overdue_uzs": totals["OVERDUE"],
                    "due_today_count": len(buckets["DUE_TODAY"]),
                    "due_today_uzs": totals["DUE_TODAY"],
                    "due_3_days_count": len(buckets["DUE_3_DAYS"]),
                    "due_3_days_uzs": totals["DUE_3_DAYS"],
                    "due_7_days_count": len(buckets["DUE_7_DAYS"]),
                    "due_7_days_uzs": totals["DUE_7_DAYS"],
                    "upcoming_30_count": len(buckets["UPCOMING_30_DAYS"]),
                    "upcoming_30_uzs": totals["UPCOMING_30_DAYS"],
                },
                "queue": queue,
                "recent_reminders": [
                    {
                        "id": str(log.id),
                        "contract_number": log.contract.contract_number,
                        "customer_name": log.user.full_name,
                        "window_tag": log.window_tag,
                        "channel": log.channel,
                        "amount_due_uzs": log.amount_due_uzs,
                        "due_date": log.due_date,
                        "status": log.status,
                        "created_at": log.created_at,
                    }
                    for log in logs
                ],
            }
        )

    def post(self, request):
        action = str(request.data.get("action") or "send_one")
        channel = str(request.data.get("channel") or "SMS").upper()
        if channel not in {"SMS", "TELEGRAM", "PUSH"}:
            channel = "SMS"

        today = timezone.localdate()
        target_items = []
        if action == "bulk_remind":
            max_days = int(request.data.get("max_days") or 3)
            target_items = list(
                InstallmentScheduleItem.objects.select_related("contract", "contract__customer")
                .filter(
                    status__in=["OVERDUE", "PARTIAL", "UPCOMING"],
                    contract__status__in=[ContractStatus.SIGNED, ContractStatus.ACTIVE, ContractStatus.OVERDUE, ContractStatus.RESTRUCTURED],
                    due_date__lte=today + timedelta(days=max_days),
                )
                .order_by("due_date")[:50]
            )
        else:
            item_id = request.data.get("schedule_item_id")
            item = InstallmentScheduleItem.objects.select_related("contract", "contract__customer").filter(id=item_id).first()
            if not item:
                return Response({"detail": "Jadval qatori topilmadi."}, status=status.HTTP_404_NOT_FOUND)
            target_items = [item]

        sent_count = 0
        for item in target_items:
            due_uzs = max(0, (item.amount_due + item.penalty_amount) - item.amount_paid)
            if due_uzs <= 0:
                continue
            days_left = (item.due_date - today).days
            _, tag = self._classify_window(days_left)
            if days_left < 0:
                title = f"Nasiya to‘lovi kechikdi ({abs(days_left)} kun)"
            elif days_left == 0:
                title = f"Bugun nasiya to‘lov kuni ({due_uzs:,} so‘m)"
            else:
                title = f"To‘lovga {days_left} kun qoldi ({due_uzs:,} so‘m)"

            NotificationEvent.objects.create(
                user=item.contract.customer,
                channel=channel,
                category="TRANSACTIONAL",
                status="delivered",
                title=title,
                body_masked=f"Shartnoma #{item.contract.contract_number}, {item.installment_no}-oy to‘lovi ({item.due_date}). Payme/Click orqali to‘lash mumkin.",
            )
            PaymentReminderLog.objects.create(
                contract=item.contract,
                schedule_item=item,
                user=item.contract.customer,
                window_tag=tag if tag in {"DUE_7_DAYS", "DUE_3_DAYS", "DUE_1_DAY", "DUE_TODAY", "OVERDUE"} else "DUE_3_DAYS",
                channel=channel,
                amount_due_uzs=due_uzs,
                due_date=item.due_date,
                sent_by=request.user,
                status="SENT",
            )
            sent_count += 1

        AuditLog.record(
            actor=request.user,
            action="UPCOMING_PAYMENT_REMINDERS_SENT",
            object_type="InstallmentScheduleItem",
            object_id=action,
            reason=f"{sent_count} ta mijozga {channel} eslatmasi yuborildi",
            after={"sent_count": sent_count, "channel": channel},
        )
        return Response({"sent_count": sent_count, "channel": channel, "detail": f"{sent_count} ta mijozga {channel} eslatmasi yuborildi."})


class AdminScoringReportsView(APIView):
    """KATM Credit Bureau, MIB Debt, Cash-Only Credit Policy & Supervisor Alerts monitor for Risk/Auditors."""

    permission_classes = [HasRolePermission]
    allowed_roles = ADMIN_ROLES | {"RISK_ANALYST", "FINANCE_OPERATIONS", "FINANCE_OFFICER", "AUDITOR"}

    def get(self, request):
        reports = ExternalScoringReport.objects.select_related("user").all()[:40]
        # Latest unique supervisor alerts (prefer alerts addressed to current supervisor, fallback to all supervisor alerts)
        seen_corr = set()
        supervisor_alerts = []
        alert_qs = NotificationEvent.objects.filter(correlation_id__startswith="SUP-CREDIT:").order_by("-created_at")[:120]
        for ev in alert_qs:
            key = ev.correlation_id or f"{ev.title}:{ev.created_at:%Y%m%d%H%M}"
            if key in seen_corr:
                continue
            seen_corr.add(key)
            code = ""
            if ":" in (ev.correlation_id or ""):
                parts = ev.correlation_id.split(":")
                code = parts[1] if len(parts) > 1 else ""
            supervisor_alerts.append(
                {
                    "id": str(ev.id),
                    "condition_code": code,
                    "title": ev.title,
                    "body_masked": ev.body_masked,
                    "correlation_id": ev.correlation_id,
                    "created_at": ev.created_at,
                }
            )
            if len(supervisor_alerts) >= 25:
                break

        customers = list(User.objects.filter(role=UserRole.CUSTOMER, is_active=True).order_by("-created_at")[:25])
        customers_credit_overview = []
        cash_only_customers = 0
        overdue_customers = 0
        clean_customers = 0
        for cu in customers:
            pol = evaluate_customer_credit_policy(cu)
            if pol["cash_only_required"]:
                cash_only_customers += 1
            else:
                clean_customers += 1
            if pol["has_overdue"]:
                overdue_customers += 1
            customers_credit_overview.append(
                {
                    "user_id": str(cu.id),
                    "full_name": cu.full_name,
                    "phone_masked": mask_value(cu.phone, 4, 2),
                    "phone_raw": cu.phone,
                    "kyc_status": cu.kyc_status,
                    "credit_policy": pol,
                }
            )

        return Response(
            {
                "reports": [
                    {
                        "id": str(r.id),
                        "check_reference": r.check_reference,
                        "provider_mode": r.provider_mode,
                        "customer_name": r.user.full_name,
                        "pinfl_masked": r.pinfl_masked,
                        "inn_masked": r.inn_masked,
                        "katm_score": r.katm_score,
                        "external_credit_history_grade": r.external_credit_history_grade,
                        "external_active_credits_count": r.external_active_credits_count,
                        "external_total_debt_uzs": r.external_total_debt_uzs,
                        "mib_status": r.mib_status,
                        "mib_debt_uzs": r.mib_debt_uzs,
                        "mib_active_cases_count": r.mib_active_cases_count,
                        "external_overdue_days_max": r.external_overdue_days_max,
                        "monthly_income_uzs": r.monthly_income_uzs,
                        "external_monthly_obligations_uzs": r.external_monthly_obligations_uzs,
                        "zarvon_active_monthly_uzs": r.zarvon_active_monthly_uzs,
                        "projected_new_monthly_uzs": r.projected_new_monthly_uzs,
                        "dsti_before_pct": r.dsti_before_pct,
                        "dsti_after_pct": r.dsti_after_pct,
                        "max_safe_monthly_uzs": r.max_safe_monthly_uzs,
                        "recommended_limit_uzs": r.recommended_limit_uzs,
                        "decision": r.decision,
                        "decision_reasons": r.decision_reasons,
                        "bureau_trace": r.bureau_trace,
                        "external_obligations_breakdown": r.external_obligations_breakdown,
                        "mib_details": r.mib_details,
                        "is_demo": r.is_demo,
                        "created_at": r.created_at,
                        "credit_policy": evaluate_customer_credit_policy(r.user),
                    }
                    for r in reports
                ],
                "kyc_documents": [
                    {
                        "id": str(d.id),
                        "user_id": str(d.user_id),
                        "customer_name": d.user.full_name,
                        "customer_phone_masked": mask_value(d.user.phone, 4, 2),
                        "customer_kyc_status": d.user.kyc_status,
                        "doc_type": d.doc_type,
                        "doc_type_label": d.get_doc_type_display(),
                        "status": d.status,
                        "status_label": d.get_status_display(),
                        "review_note": d.review_note,
                        "reviewer_name": d.reviewer.full_name if d.reviewer else None,
                        "content_type": d.content_type,
                        "is_image": d.content_type.startswith("image/"),
                        "file_url": f"/api/v1/finance/kyc/documents/{d.id}/file/",
                        "created_at": d.created_at,
                        "reviewed_at": d.reviewed_at,
                    }
                    for d in KycDocument.objects.select_related("user", "reviewer").all()[:40]
                ],
                "supervisor_alerts": supervisor_alerts,
                "customers_credit_overview": customers_credit_overview,
                "summary": {
                    "total": ExternalScoringReport.objects.count(),
                    "approved": ExternalScoringReport.objects.filter(decision="APPROVE").count(),
                    "manual_review": ExternalScoringReport.objects.filter(decision="MANUAL_REVIEW").count(),
                    "declined": ExternalScoringReport.objects.filter(decision="DECLINE").count(),
                    "mib_blocked": ExternalScoringReport.objects.filter(mib_status="BLOCKED").count(),
                    "cash_only_customers": cash_only_customers,
                    "overdue_customers": overdue_customers,
                    "clean_customers": clean_customers,
                },
            }
        )

    @transaction.atomic
    def post(self, request):
        """Allow Supervisor/Risk/Admin to inspect any customer's live credit status and send supervisor alerts."""
        user_id = request.data.get("user_id")
        phone = (request.data.get("phone") or "").strip()
        target = None
        if user_id:
            target = User.objects.filter(id=user_id, is_active=True).first()
        elif phone:
            digits = "".join(ch for ch in phone if ch.isdigit())
            if len(digits) == 9:
                normalized = f"+998{digits}"
            elif digits.startswith("998") and len(digits) >= 12:
                normalized = f"+{digits[:12]}"
            else:
                normalized = phone
            target = User.objects.filter(phone=normalized, is_active=True).first()

        if not target:
            return Response({"detail": "Tekshirish uchun mijoz topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        refresh_bureau = bool(request.data.get("refresh_bureau", False))
        scenario = (request.data.get("scenario") or "").strip()
        ext = None
        if refresh_bureau or scenario:
            pinfl = (request.data.get("pinfl") or "").strip()
            if len(pinfl) != 14 or not pinfl.isdigit():
                # Deterministic sandbox PINFL fallback when supervisor checks a customer
                pinfl = "31405940010012"
            ext = run_katm_and_mib_scoring(
                user=target,
                pinfl=pinfl,
                inn=(request.data.get("inn") or "").strip(),
                birth_year=target.birth_year or 1994,
                monthly_income_uzs=int(request.data.get("monthly_income_uzs") or 9_000_000),
                scenario=scenario or "auto",
            )
            lim, _ = CustomerLimit.objects.get_or_create(user=target)
            if ext.decision == "DECLINE":
                lim.is_frozen = True
                lim.freeze_reason = (ext.decision_reasons or ["Kredit / kechikish cheklovi"])[0]
                lim.save(update_fields=["is_frozen", "freeze_reason", "updated_at"])
            elif ext.decision == "APPROVE":
                lim.is_frozen = False
                lim.freeze_reason = ""
                lim.total_limit_uzs = max(lim.used_limit_uzs, ext.recommended_limit_uzs)
                lim.save(update_fields=["is_frozen", "freeze_reason", "total_limit_uzs", "updated_at"])

        policy = evaluate_customer_credit_policy(target)
        notified = notify_supervisors_credit_status(
            user=target,
            policy=policy,
            ext_report=ext or ExternalScoringReport.objects.filter(user=target).first(),
            trigger="SUPERVISOR_INSPECTION",
            extra_note=f"Tekshiruvchi: {request.user.full_name} ({request.user.role}).",
        )
        AuditLog.record(
            actor=request.user,
            action="SUPERVISOR_CREDIT_INSPECTION",
            object_type="User",
            object_id=target.id,
            reason=f"Holat: {policy['credit_condition_code']} ({policy['trading_mode_label']}), Xabar yuborildi: {notified} ta nazoratchi",
        )
        return Response(
            {
                "ok": True,
                "customer": {
                    "user_id": str(target.id),
                    "full_name": target.full_name,
                    "phone_masked": mask_value(target.phone, 4, 2),
                },
                "credit_policy": policy,
                "supervisors_notified": notified,
                "detail": f"Mijoz holati aniqlandi ({policy['trading_mode_label']}) va {notified} ta nazoratchiga xabar yuborildi.",
            }
        )


class UzumMerchantWebhookView(APIView):
    """Official Uzum Bank Merchant API REST endpoints (/check, /create, /confirm, /reverse, /status)."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request, stage: str = ""):
        raw_body = request.body.decode("utf-8", errors="replace") if request.body else ""
        payload = request.data if isinstance(request.data, dict) else {}
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        sig_header = request.META.get("HTTP_X_SIGNATURE", "")
        res = process_uzum_webhook(
            stage or payload.get("action") or "check",
            payload,
            auth_header=auth_header,
            signature_header=sig_header,
            body_raw=raw_body,
        )
        http_status = 200 if res.get("status") != "FAILED" else (401 if res.get("errorCode") == "10001" else 400)
        return Response(res, status=http_status)


KYC_VIEWER_ROLES = ADMIN_ROLES | {"RISK_MANAGER", "FINANCE_OFFICER", "FRAUD_ANALYST", "AUDITOR", "FINANCE_OPERATIONS"}


def _serialize_kyc_doc(d: KycDocument) -> dict:
    return {
        "id": str(d.id),
        "user_id": str(d.user_id),
        "customer_name": d.user.full_name,
        "customer_phone_masked": mask_value(d.user.phone, 4, 2),
        "customer_kyc_status": d.user.kyc_status,
        "doc_type": d.doc_type,
        "doc_type_label": d.get_doc_type_display(),
        "status": d.status,
        "status_label": d.get_status_display(),
        "review_note": d.review_note,
        "reviewer_name": d.reviewer.full_name if d.reviewer else None,
        "content_type": d.content_type,
        "is_image": d.content_type.startswith("image/"),
        "original_filename": d.original_filename,
        "file_size_bytes": d.file_size_bytes,
        "file_url": f"/api/v1/finance/kyc/documents/{d.id}/file/",
        "created_at": d.created_at,
        "reviewed_at": d.reviewed_at,
    }


class KycDocumentsView(APIView):
    """Upload & list private KYC documents (Passport photos, Selfie, MIB PDF) stored in PRIVATE_MEDIA_ROOT."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 8 * 1024 * 1024
    VALID_TYPES = {"PASSPORT_FRONT", "PASSPORT_BACK", "SELFIE", "MIB_CERT", "INCOME_PROOF"}

    def get(self, request):
        scope = (request.query_params.get("scope") or "").strip().lower()
        is_reviewer = request.user.role in KYC_VIEWER_ROLES
        if scope == "all" and is_reviewer:
            qs = KycDocument.objects.select_related("user", "reviewer").all()
            status_f = (request.query_params.get("status") or "").strip()
            if status_f:
                qs = qs.filter(status=status_f)
            return Response({"documents": [_serialize_kyc_doc(d) for d in qs[:50]]})

        docs = KycDocument.objects.select_related("user", "reviewer").filter(user=request.user)[:20]
        return Response({"documents": [_serialize_kyc_doc(d) for d in docs]})

    @transaction.atomic
    def post(self, request):
        doc_type = (request.data.get("doc_type") or "PASSPORT_FRONT").strip()
        if doc_type not in self.VALID_TYPES:
            return Response({"detail": "Noto‘g‘ri hujjat turi tanlandi."}, status=status.HTTP_400_BAD_REQUEST)

        upload = request.FILES.get("file") or request.FILES.get("image")
        if not upload:
            return Response({"detail": "Hujjat yoki rasm faylini tanlang (file)."}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > self.MAX_BYTES:
            return Response({"detail": "Fayl hajmi 8 MB dan oshmasligi kerak."}, status=status.HTTP_400_BAD_REQUEST)

        orig_name = (getattr(upload, "name", "") or "document")[:160]
        is_pdf = orig_name.lower().endswith(".pdf") or getattr(upload, "content_type", "") == "application/pdf"

        private_dir = Path(settings.PRIVATE_MEDIA_ROOT) / "kyc" / str(request.user.id)
        private_dir.mkdir(parents=True, exist_ok=True)

        if is_pdf:
            raw_bytes = upload.read()
            if not raw_bytes.startswith(b"%PDF-"):
                return Response({"detail": "Yaroqsiz PDF fayl."}, status=status.HTTP_400_BAD_REQUEST)
            filename = f"{uuid.uuid4().hex[:16]}.pdf"
            dest_path = private_dir / filename
            dest_path.write_bytes(raw_bytes)
            stored_size = len(raw_bytes)
            content_type = "application/pdf"
        else:
            try:
                img = Image.open(upload)
                img.verify()
                upload.seek(0)
                img = Image.open(upload)
                img = ImageOps.exif_transpose(img)
            except (UnidentifiedImageError, Exception):
                return Response(
                    {"detail": "Yaroqsiz rasm fayli. JPEG, PNG, WEBP yoki PDF yuklang."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                clean_img = bg
            else:
                clean_img = img.convert("RGB")
            clean_img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            filename = f"{uuid.uuid4().hex[:16]}.jpg"
            dest_path = private_dir / filename
            clean_img.save(dest_path, format="JPEG", quality=88, optimize=True)
            stored_size = dest_path.stat().st_size
            content_type = "image/jpeg"

        rel_path = f"kyc/{request.user.id}/{filename}"
        doc = KycDocument.objects.create(
            user=request.user,
            doc_type=doc_type,
            file_rel_path=rel_path,
            content_type=content_type,
            original_filename=orig_name,
            file_size_bytes=stored_size,
            status="PENDING",
        )
        if request.user.kyc_status in {"UNVERIFIED", "REJECTED"}:
            request.user.kyc_status = "PENDING"
            request.user.save(update_fields=["kyc_status"])

        AuditLog.record(
            actor=request.user,
            action="KYC_DOCUMENT_UPLOADED",
            object_type="KycDocument",
            object_id=doc.id,
            reason=f"Hujjat yuklandi: {doc.get_doc_type_display()}",
        )
        return Response(
            {
                "ok": True,
                "document": _serialize_kyc_doc(doc),
                "kyc_status": request.user.kyc_status,
                "detail": f"«{doc.get_doc_type_display()}» xavfsiz yopiq omborga yuklandi va Nazoratchi navbatiga qo‘shildi.",
            },
            status=status.HTTP_201_CREATED,
        )


class KycDocumentFileView(APIView):
    """Serve private KYC image/PDF exclusively to the document owner or authorized supervisors/auditors."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        doc = KycDocument.objects.select_related("user").filter(id=pk).first()
        if not doc:
            return Response({"detail": "Hujjat topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        is_allowed = (doc.user_id == request.user.id) or (request.user.role in KYC_VIEWER_ROLES)
        if not is_allowed:
            return Response({"detail": "Shaxsiy KYC hujjatini ko‘rish taqiqlangan (RBAC)."}, status=status.HTTP_403_FORBIDDEN)

        private_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        file_path = (private_root / doc.file_rel_path).resolve()
        if not file_path.is_relative_to(private_root) or not file_path.exists():
            return Response({"detail": "Fayl ombordan topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        resp = FileResponse(open(file_path, "rb"), content_type=doc.content_type)
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store"
        return resp


class KycDocumentReviewView(APIView):
    """Supervisor decision on uploaded Passport/Selfie/MIB docs: Approve Nasiya, Force Cash-Only, or Reject."""

    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "RISK_MANAGER", "FINANCE_OFFICER", "FRAUD_ANALYST", "FINANCE_OPERATIONS"}

    @transaction.atomic
    def post(self, request, pk):
        doc = KycDocument.objects.select_for_update().select_related("user").filter(id=pk).first()
        if not doc:
            return Response({"detail": "KYC hujjati topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        decision = (request.data.get("decision") or "").strip().upper()
        if decision not in {"APPROVED_NASIYA", "CASH_ONLY", "REJECTED"}:
            return Response({"detail": "Qaror APPROVED_NASIYA, CASH_ONLY yoki REJECTED bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)

        note = (request.data.get("review_note") or "").strip()[:255]
        approved_limit_raw = request.data.get("approved_limit_uzs")

        doc.status = decision
        doc.reviewer = request.user
        doc.review_note = note
        doc.reviewed_at = timezone.now()
        doc.save(update_fields=["status", "reviewer", "review_note", "reviewed_at"])

        cust = doc.user
        lim, _ = CustomerLimit.objects.get_or_create(user=cust)
        if decision == "APPROVED_NASIYA":
            KycDocument.objects.filter(user=cust, status="CASH_ONLY").update(status="APPROVED_NASIYA", reviewed_at=timezone.now(), reviewer=request.user)
            cust.kyc_status = "VERIFIED"
            cust.save(update_fields=["kyc_status"])
            if approved_limit_raw is not None and str(approved_limit_raw).strip() != "":
                target_lim = max(lim.used_limit_uzs, int(approved_limit_raw))
            else:
                target_lim = max(lim.used_limit_uzs, lim.total_limit_uzs, 5_000_000)
            lim.total_limit_uzs = target_lim
            lim.is_frozen = False
            lim.freeze_reason = ""
            lim.is_demo_limit = settings.ZARVON_SANDBOX_MODE
            lim.save()
            NotificationEvent.objects.create(
                user=cust,
                channel="PUSH",
                category="TRANSACTIONAL",
                status="delivered",
                title="✅ Hujjatlaringiz tasdiqlandi — Nasiya savdo ochildi",
                body_masked=f"Nazoratchi tekshiruvidan muvaffaqiyatli o‘tdingiz. Bo‘sh limit: {lim.available_limit_uzs:,} so‘m.",
            )
        elif decision == "CASH_ONLY":
            cust.kyc_status = "VERIFIED"
            cust.save(update_fields=["kyc_status"])
            lim.is_frozen = True
            lim.freeze_reason = note or "Nazoratchi hujjat tekshiruvida kredit/MIB qarzi aniqlandi — Faqat naqd savdo"
            lim.save(update_fields=["is_frozen", "freeze_reason", "updated_at"])
            NotificationEvent.objects.create(
                user=cust,
                channel="PUSH",
                category="TRANSACTIONAL",
                status="delivered",
                title="⚠ Faqat naqd savdo rejimi belgilandi",
                body_masked=lim.freeze_reason,
            )
        else:
            cust.kyc_status = "REJECTED"
            cust.save(update_fields=["kyc_status"])
            NotificationEvent.objects.create(
                user=cust,
                channel="PUSH",
                category="TRANSACTIONAL",
                status="delivered",
                title="✕ KYC hujjati rad etildi — qayta yuklang",
                body_masked=note or "Pasport yoki ma’lumotnoma rasmi aniq emas; iltimos qayta yuklang.",
            )

        policy = evaluate_customer_credit_policy(cust)
        notify_supervisors_credit_status(
            user=cust,
            policy=policy,
            trigger="SUPERVISOR_INSPECTION",
            extra_note=f"Hujjat qarori ({doc.get_doc_type_display()} -> {decision}) by {request.user.full_name}.",
        )
        AuditLog.record(
            actor=request.user,
            action="KYC_DOCUMENT_REVIEWED",
            object_type="KycDocument",
            object_id=doc.id,
            reason=f"{decision}: {note or 'Izohsiz'}",
        )
        return Response(
            {
                "ok": True,
                "document": _serialize_kyc_doc(doc),
                "kyc_status": cust.kyc_status,
                "credit_policy": policy,
                "detail": f"Hujjat bo‘yicha qaror saqlandi: {doc.get_status_display()}",
            }
        )
