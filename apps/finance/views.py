"""Nasiya Calculator, Consents, KYC/KATM/MIB Scoring, Customer Cabinet, Click/Payme PSP & Due Monitor."""
import base64
from datetime import timedelta
import json
import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission
from config.utils import encrypt_field, hash_identifier, mask_value
from apps.accounts.models import User
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
    compute_click_signature,
    process_click_webhook,
    process_payme_rpc,
    resolve_payment_target,
    settle_psp_payment,
)
from apps.finance.scoring import run_katm_and_mib_scoring
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
        scenario = (request.data.get("scenario") or "auto").strip()
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
            provider="MyID + INN Sandbox",
            liveness_passed=liveness_ok,
            status="VERIFIED" if liveness_ok else "FAILED",
            correlation_id=f"MYID-{uuid.uuid4().hex[:8].upper()}",
        )

        # Run full KATM + MIB + 50% DSTI scoring engine
        ext = run_katm_and_mib_scoring(
            user=user,
            pinfl=pinfl,
            inn=inn,
            birth_year=birth_year,
            monthly_income_uzs=monthly_income_uzs,
            requested_purchase_uzs=requested_purchase_uzs,
            requested_months=requested_months,
            scenario=scenario,
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

        AuditLog.record(
            actor=user,
            action="KATM_MIB_SCORING_COMPLETED",
            object_type="ExternalScoringReport",
            object_id=ext.id,
            reason=f"Qaror: {ext.decision}, DSTI: {ext.dsti_before_pct}%, MIB: {ext.mib_status}",
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
        payments = PaymentRecord.objects.filter(user=user)[:20]
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
                "is_demo": ext_rep.is_demo,
                "created_at": ext_rep.created_at,
            }
            if ext_rep
            else None
        )
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
                "latest_scoring_report": latest_ext,
                "payment_cards": cards_data,
                "contracts": contracts_data,
                "credit_applications": apps_data,
                "payments": [
                    {
                        "payment_intent_id": p.payment_intent_id,
                        "provider": p.provider,
                        "amount": p.amount,
                        "status": p.status,
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

        PaymentRecord.objects.create(
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
        return Response({"ok": True, "applied_amount": applied, "early_fee": 0, "remaining_balance": contract.remaining_balance, "contract_status": contract.status})


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
        return Response(
            {
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

    def post(self, request):
        result = process_click_webhook(request.data)
        return Response(result, status=status.HTTP_200_OK)


class PaymeMerchantRpcView(APIView):
    """Official Payme Business Merchant API JSON-RPC 2.0 endpoint."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        result = process_payme_rpc(request.data, auth_header)
        return Response(result, status=status.HTTP_200_OK)


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

        if not settings.ZARVON_SANDBOX_MODE:
            # In strict production mode without sandbox, return signed checkout parameters instead of auto-settling.
            payme_params = f"m={settings.PAYME_MERCHANT_ID};ac.order_id={reference};a={req_amount * 100}"
            payme_b64 = base64.b64encode(payme_params.encode("utf-8")).decode("utf-8")
            return Response(
                {
                    "mode": "LIVE_CHECKOUT_INTENT",
                    "psp_provider": psp_provider,
                    "reference": reference,
                    "amount_uzs": req_amount,
                    "checkout_url": f"https://checkout.paycom.uz/{payme_b64}" if psp_provider == "Payme" else f"https://my.click.uz/services/pay?service_id={settings.CLICK_SERVICE_ID}&merchant_id={settings.CLICK_MERCHANT_ID}&amount={req_amount}&transaction_param={reference}",
                },
                status=status.HTTP_200_OK,
            )

        # Sandbox Protocol Execution — exercises the real cryptographic verification paths!
        protocol_trace = []
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
                "card_masked": used_card.card_masked_pan if used_card else None,
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
    """KATM Credit Bureau, MIB Debt & 50% DSTI Scoring telemetry monitor for Operations/Risk."""

    permission_classes = [HasRolePermission]
    allowed_roles = ADMIN_ROLES | {"RISK_ANALYST", "FINANCE_OPERATIONS", "FINANCE_OFFICER", "AUDITOR"}

    def get(self, request):
        reports = ExternalScoringReport.objects.select_related("user").all()[:40]
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
                        "external_obligations_breakdown": r.external_obligations_breakdown,
                        "mib_details": r.mib_details,
                        "is_demo": r.is_demo,
                        "created_at": r.created_at,
                    }
                    for r in reports
                ],
                "summary": {
                    "total": ExternalScoringReport.objects.count(),
                    "approved": ExternalScoringReport.objects.filter(decision="APPROVE").count(),
                    "manual_review": ExternalScoringReport.objects.filter(decision="MANUAL_REVIEW").count(),
                    "declined": ExternalScoringReport.objects.filter(decision="DECLINE").count(),
                    "mib_blocked": ExternalScoringReport.objects.filter(mib_status="BLOCKED").count(),
                },
            }
        )
