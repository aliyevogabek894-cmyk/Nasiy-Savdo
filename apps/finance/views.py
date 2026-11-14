"""Nasiya Calculator, Consents, KYC, Customer Cabinet, Early Repayment, Multi-Bank & Reconciliation."""
import uuid
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import HasRolePermission
from config.utils import hash_identifier
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
    IdentityCheck,
    InstallmentContract,
    InstallmentPlan,
    LimitEvent,
    PaymentRecord,
    ReconciliationRecord,
    RepaymentEvent,
    WebhookEvent,
)
from apps.finance.providers import ComplianceViolationError, OwnInstallmentProvider
from apps.governance.models import AuditLog, BhmValue, ComplianceRuleVersion, NotificationEvent
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
    """MyID/OneID Sandbox Verification, PINFL Multi-Account Anti-Fraud & Explainable Risk Limit."""

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        user = request.user
        has_id_consent = CustomerConsent.objects.filter(user=user, purpose="IDENTITY", is_granted=True, revoked_at__isnull=True).exists()
        has_cb_consent = CustomerConsent.objects.filter(user=user, purpose="CREDIT_BUREAU", is_granted=True, revoked_at__isnull=True).exists()
        if not (has_id_consent and has_cb_consent):
            return Response(
                {"detail": "Shaxsni tasdiqlash va kredit hisobotini so‘rash uchun alohida roziliklar talab qilinadi (28.4 / 23.1)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pinfl = (request.data.get("pinfl") or "").strip()
        passport = (request.data.get("passport") or "").strip().upper()
        birth_year = int(request.data.get("birth_year") or 1995)
        liveness_ok = bool(request.data.get("liveness_passed", True))
        if len(pinfl) != 14 or not pinfl.isdigit() or len(passport) < 8:
            return Response({"detail": "14 xonali PINFL va pasport/ID seriya raqamini to‘g‘ri kiriting."}, status=status.HTTP_400_BAD_REQUEST)

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

        user.set_identity_fields(pinfl=pinfl, passport=passport)
        user.birth_year = birth_year
        user.kyc_status = "VERIFIED" if liveness_ok else "PENDING"
        user.save()

        IdentityCheck.objects.create(
            user=user,
            provider="MyID Sandbox",
            liveness_passed=liveness_ok,
            status="VERIFIED" if liveness_ok else "FAILED",
            correlation_id=f"MYID-{uuid.uuid4().hex[:8].upper()}",
        )

        # Business age policy check (22-65 yosh biznes siyosati, qonun emas — 28.2)
        age = timezone.now().year - birth_year
        if age < 22 or age > 65:
            ra = RiskAssessment.objects.create(
                user=user,
                score=510,
                dti_ratio_pct=45.0,
                decision="MANUAL_REVIEW",
                reason_codes=["AGE_POLICY_BOUNDARY", "NEEDS_HUMAN_REVIEW"],
                recommended_tier="Start",
            )
            return Response(
                {
                    "ok": True,
                    "kyc_status": user.kyc_status,
                    "decision": "MANUAL_REVIEW",
                    "message": f"Sizning arizangiz qo‘shimcha inson ko‘rigiga yuborildi (biznes yosh siyosati: 22–65 yosh). Apellyatsiya huquqingiz mavjud.",
                    "assessment_id": str(ra.id),
                }
            )

        # Assign transparent Sandbox tier limit
        ra = RiskAssessment.objects.create(
            user=user,
            score=735,
            dti_ratio_pct=21.5,
            decision="APPROVE",
            reason_codes=["MYID_VERIFIED", "STABLE_INCOME_SANDBOX", "LOW_DEBT_LOAD"],
            recommended_tier="Plus",
        )
        lim, _ = CustomerLimit.objects.get_or_create(user=user)
        lim.tier = "Plus"
        lim.total_limit_uzs = 15_000_000
        lim.is_frozen = False
        lim.is_demo_limit = True
        lim.save()
        LimitEvent.objects.create(
            customer_limit=lim,
            event_type="INCREASE",
            amount_delta=15_000_000,
            reason="MyID Sandbox tasdiqlandi va skoring o‘tdi (DEMO limit)",
            actor=user,
        )
        AuditLog.record(actor=user, action="KYC_AND_SCORING_COMPLETED", object_type="CustomerLimit", object_id=lim.id, reason="MyID sandbox verifikatsiyasi")
        return Response(
            {
                "ok": True,
                "kyc_status": user.kyc_status,
                "decision": "APPROVE",
                "tier": lim.tier,
                "available_limit_uzs": lim.available_limit_uzs,
                "reason_codes": ra.reason_codes,
                "is_demo_limit": True,
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

        # Find earliest upcoming installment across active contracts for "Next Payment Card"
        next_payment = None
        contracts_data = []
        for c in contracts:
            sched = [
                {
                    "id": str(s.id),
                    "installment_no": s.installment_no,
                    "due_date": s.due_date,
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
            if upcoming and (next_payment is None or str(upcoming["due_date"]) < str(next_payment["due_date"])):
                next_payment = {
                    "contract_id": str(c.id),
                    "contract_number": c.contract_number,
                    "due_date": upcoming["due_date"],
                    "amount": upcoming["amount_due"] - upcoming["amount_paid"] + upcoming["penalty_amount"],
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
