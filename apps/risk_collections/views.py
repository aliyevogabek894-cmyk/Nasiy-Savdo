"""Executive KPIs, Risk Appeals, Fraud Cases, DPD Collections, Maker-Checker Restructuring & Support."""
import uuid
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission
from apps.accounts.models import User
from apps.catalog.models import Product, ProductStatus
from apps.commerce.models import Order, OrderStatus, ReturnRequest
from apps.finance.models import BankPartner, ContractStatus, InstallmentContract, PaymentRecord
from apps.governance.models import AuditLog, SecurityEvent
from apps.inventory.models import StockLevel
from apps.risk_collections.models import (
    CollectionAction,
    CollectionCase,
    FraudCase,
    FraudSignal,
    ReceivableAssignment,
    RestructuringCase,
    RiskAssessment,
    SupportTicket,
)
from apps.sellers.models import SellerApplication, SellerOnboardingStatus, Store


class AdminDashboardView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = ADMIN_ROLES

    def get(self, request):
        orders = Order.objects.all()
        total_orders = orders.count()
        gmv = sum(o.total_amount for o in orders.exclude(status=OrderStatus.CANCELLED))
        cancelled_cnt = orders.filter(status=OrderStatus.CANCELLED).count()
        returns_cnt = ReturnRequest.objects.count()
        contracts = InstallmentContract.objects.all()
        active_portfolio = sum(c.remaining_balance for c in contracts.filter(status__in=[ContractStatus.ACTIVE, ContractStatus.SIGNED, ContractStatus.OVERDUE]))
        overdue_portfolio = sum(c.remaining_balance for c in contracts.filter(status=ContractStatus.OVERDUE))
        par30_pct = round((overdue_portfolio / active_portfolio * 100.0), 1) if active_portfolio > 0 else 0.0

        low_stock_cnt = sum(1 for s in StockLevel.objects.all() if s.is_low_stock)
        banks = BankPartner.objects.all()
        banks_online = sum(1 for b in banks if b.adapter_status == "ONLINE")

        return Response(
            {
                "kpis": {
                    "gmv_uzs": gmv,
                    "total_orders": total_orders,
                    "cancel_rate_pct": round((cancelled_cnt / total_orders * 100.0), 1) if total_orders else 0.0,
                    "return_count": returns_cnt,
                    "pending_seller_apps": SellerApplication.objects.filter(status__in=[SellerOnboardingStatus.SUBMITTED, SellerOnboardingStatus.UNDER_REVIEW]).count(),
                    "active_stores": Store.objects.filter(status="Active").count(),
                    "moderation_queue": Product.objects.filter(status=ProductStatus.PENDING_REVIEW).count(),
                    "active_nasiya_contracts": contracts.count(),
                    "active_portfolio_uzs": active_portfolio,
                    "par30_pct": par30_pct,
                    "low_stock_alerts": low_stock_cnt,
                    "open_security_alerts": SecurityEvent.objects.filter(resolved=False).count(),
                    "open_fraud_cases": FraudCase.objects.filter(status__in=["OPEN", "UNDER_REVIEW"]).count(),
                    "open_tickets": SupportTicket.objects.filter(status__in=["OPEN", "IN_PROGRESS"]).count(),
                    "banks_online": f"{banks_online}/{banks.count()}",
                },
                "funnel": [
                    {"stage": "Katalog ko‘rish", "count": 14820, "pct": 100},
                    {"stage": "Savatga qo‘shish", "count": 3420, "pct": 23.1},
                    {"stage": "Kassa bosqichi", "count": 1240, "pct": 8.4},
                    {"stage": "Nasiya / Bank ariza", "count": max(610, contracts.count() * 48), "pct": 4.1},
                    {"stage": "Tasdiqlangan buyurtma", "count": max(420, total_orders), "pct": 2.9},
                ],
                "customer_360_preview": [
                    {
                        "id": str(u.id),
                        "full_name": u.full_name,
                        "phone": u.phone,
                        "kyc_status": u.kyc_status,
                        "masked_pinfl": u.get_masked_pinfl(),
                        "orders_count": u.orders.count(),
                        "contracts_count": u.installment_contracts.count(),
                    }
                    for u in User.objects.filter(role="CUSTOMER")[:15]
                ],
            }
        )


class RiskAssessmentsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.role in {"SUPER_ADMIN", "RISK_MANAGER", "FINANCE_OFFICER", "AUDITOR"}:
            qs = RiskAssessment.objects.select_related("user").all()[:30]
        else:
            qs = RiskAssessment.objects.filter(user=request.user)[:10]
        return Response(
            {
                "results": [
                    {
                        "id": str(r.id),
                        "user_name": r.user.full_name,
                        "model_version": r.model_version,
                        "score": r.score,
                        "dti_ratio_pct": r.dti_ratio_pct,
                        "decision": r.decision,
                        "reason_codes": r.reason_codes,
                        "recommended_tier": r.recommended_tier,
                        "appeal_status": r.appeal_status,
                        "created_at": r.created_at,
                    }
                    for r in qs
                ]
            }
        )

    def post(self, request):
        """Customer appeal OR Risk Manager human override (Section 9)."""
        ra = RiskAssessment.objects.filter(id=request.data.get("assessment_id")).first()
        if not ra:
            return Response({"detail": "Skoring yozuvi topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        action = request.data.get("action")
        if action == "APPEAL" and ra.user_id == request.user.id:
            ra.appeal_status = "APPEALED"
            ra.save(update_fields=["appeal_status"])
            SupportTicket.objects.create(
                ticket_number=f"APL-{uuid.uuid4().hex[:6].upper()}",
                user=request.user,
                category="RISK_APPEAL",
                subject="Skoring / limit qarori bo‘yicha apellyatsiya",
                messages=[{"sender": request.user.full_name, "text": request.data.get("reason") or "Ma’lumotlarimni qayta ko‘rib chiqishingizni so‘rayman.", "at": timezone.now().isoformat()}],
            )
            return Response({"ok": True, "appeal_status": ra.appeal_status})

        if request.user.role in {"SUPER_ADMIN", "RISK_MANAGER"} and action in {"OVERTURN", "UPHOLD"}:
            ra.appeal_status = "OVERTURNED" if action == "OVERTURN" else "UPHELD"
            ra.human_reviewed_by = request.user
            if action == "OVERTURN":
                ra.decision = "APPROVE"
            ra.save()
            AuditLog.record(actor=request.user, action=f"RISK_APPEAL_{ra.appeal_status}", object_type="RiskAssessment", object_id=ra.id, reason="Inson ko‘rigi (9-bo‘lim)")
            return Response({"ok": True, "appeal_status": ra.appeal_status})

        return Response({"detail": "Ruxsat yo‘q yoki noto‘g‘ri amal."}, status=status.HTTP_403_FORBIDDEN)


class FraudConsoleView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "FRAUD_ANALYST", "RISK_MANAGER", "AUDITOR"}

    def get(self, request):
        cases = FraudCase.objects.select_related("signal__user").all()[:30]
        return Response(
            {
                "results": [
                    {
                        "id": str(c.id),
                        "signal_type": c.signal.get_signal_type_display(),
                        "severity": c.signal.severity,
                        "summary": c.signal.summary,
                        "user_name": c.signal.user.full_name if c.signal.user else "Noma’lum",
                        "status": c.status,
                        "resolution_note": c.resolution_note,
                        "created_at": c.created_at,
                    }
                    for c in cases
                ]
            }
        )

    def post(self, request):
        fc = FraudCase.objects.filter(id=request.data.get("case_id")).first()
        if not fc:
            return Response({"detail": "Ish topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        new_status = request.data.get("status")
        note = (request.data.get("resolution_note") or "").strip()
        if new_status not in {"UNDER_REVIEW", "CLEARED", "CONFIRMED"} or not note:
            return Response({"detail": "Holat va izoh majburiy."}, status=status.HTTP_400_BAD_REQUEST)
        fc.status = new_status
        fc.assigned_to = request.user
        fc.resolution_note = note
        fc.save()
        AuditLog.record(actor=request.user, action="FRAUD_CASE_UPDATED", object_type="FraudCase", object_id=fc.id, reason=note)
        return Response({"ok": True, "status": fc.status})


class CollectionsConsoleView(APIView):
    """DPD Collections Queue, Respectful Conduct Log, Maker-Checker Restructuring & Licensed Assignment."""

    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "COLLECTIONS_AGENT", "FINANCE_OFFICER", "RISK_MANAGER", "AUDITOR"}

    def get(self, request):
        cases = CollectionCase.objects.select_related("contract__customer").prefetch_related("actions").all()[:30]
        restructs = RestructuringCase.objects.select_related("contract", "requested_by", "approved_by").all()[:20]
        return Response(
            {
                "cases": [
                    {
                        "id": str(c.id),
                        "contract_id": str(c.contract_id),
                        "contract_number": c.contract.contract_number,
                        # Collections Agent does NOT see full raw passport/PINFL (Section 33)
                        "customer_name": c.contract.customer.full_name,
                        "customer_phone": c.contract.customer.phone,
                        "dpd_days": c.dpd_days,
                        "overdue_amount_uzs": c.overdue_amount_uzs,
                        "stage": c.stage,
                        "actions": [
                            {"channel": a.channel, "note": a.note, "respectful": a.respectful_conduct_confirmed, "created_at": a.created_at}
                            for a in c.actions.all()[:5]
                        ],
                    }
                    for c in cases
                ],
                "restructuring_cases": [
                    {
                        "id": str(r.id),
                        "contract_number": r.contract.contract_number,
                        "proposed_new_months": r.proposed_new_months,
                        "reason": r.reason,
                        "status": r.status,
                        "requested_by": r.requested_by.full_name,
                        "requested_by_id": str(r.requested_by_id),
                        "approved_by": r.approved_by.full_name if r.approved_by else None,
                    }
                    for r in restructs
                ],
            }
        )

    @transaction.atomic
    def post(self, request):
        action_kind = request.data.get("action_kind")
        if action_kind == "LOG_CONTACT":
            case = CollectionCase.objects.filter(id=request.data.get("case_id")).first()
            if not case:
                return Response({"detail": "Undirish ishi topilmadi."}, status=status.HTTP_404_NOT_FOUND)
            note = (request.data.get("note") or "").strip()
            if not note or not request.data.get("respectful_conduct_confirmed", True):
                return Response({"detail": "Odob qoidalari tasdig‘i va aloqa izohi majburiy (28.5)."}, status=status.HTTP_400_BAD_REQUEST)
            CollectionAction.objects.create(
                case=case,
                actor=request.user,
                channel=request.data.get("channel") or "CALL_WORK_HOURS",
                note=note,
                respectful_conduct_confirmed=True,
            )
            return Response({"ok": True})

        if action_kind == "PROPOSE_RESTRUCTURE":
            contract = InstallmentContract.objects.filter(id=request.data.get("contract_id")).first()
            months = int(request.data.get("proposed_new_months") or 12)
            reason = (request.data.get("reason") or "").strip()
            if not contract or months > 12 or months < 1 or not reason:
                return Response({"detail": "Yangi muddat 12 oydan oshmasligi va sabab ko‘rsatilishi shart (28.5)."}, status=status.HTTP_400_BAD_REQUEST)
            rc = RestructuringCase.objects.create(
                contract=contract,
                requested_by=request.user,
                reason=reason,
                proposed_new_months=months,
            )
            return Response({"ok": True, "restructuring_id": str(rc.id)}, status=status.HTTP_201_CREATED)

        if action_kind == "DECIDE_RESTRUCTURE":
            rc = RestructuringCase.objects.select_for_update().filter(id=request.data.get("restructuring_id")).first()
            if not rc or rc.requested_by_id == request.user.id:
                return Response({"detail": "Restrukturizatsiya tasdig‘i uchun boshqa vakolatli xodim kerak (Maker-Checker: 28.5)."}, status=status.HTTP_403_FORBIDDEN)
            decision = request.data.get("decision")
            rc.status = "APPROVED" if decision == "APPROVED" else "REJECTED"
            rc.approved_by = request.user
            rc.save()
            if rc.status == "APPROVED":
                rc.contract.status = ContractStatus.RESTRUCTURED
                rc.contract.save(update_fields=["status"])
            AuditLog.record(actor=request.user, action=f"RESTRUCTURING_{rc.status}", object_type="RestructuringCase", object_id=rc.id, reason=rc.reason)
            return Response({"ok": True, "status": rc.status})

        if action_kind == "ASSIGN_RECEIVABLE":
            lic_type = request.data.get("assignee_license_type")
            if lic_type not in {"OPERATOR", "MFO", "BANK"}:
                return Response(
                    {"detail": "27.1-bo‘limga ko‘ra talab faqat Markaziy bank reestridagi nasiya operatori, MFO yoki bankka o‘tkazilishi mumkin!"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            contract = InstallmentContract.objects.filter(id=request.data.get("contract_id")).first()
            if not contract:
                return Response({"detail": "Shartnoma topilmadi."}, status=status.HTTP_404_NOT_FOUND)
            ReceivableAssignment.objects.create(
                contract=contract,
                assignee_name=request.data.get("assignee_name") or "Hamkor MFO",
                assignee_license_type=lic_type,
                registry_number=request.data.get("registry_number") or "MB-REG-2027-01",
                assigned_by=request.user,
            )
            contract.status = ContractStatus.ASSIGNED
            contract.save(update_fields=["status"])
            return Response({"ok": True})

        return Response({"detail": "Noma’lum amal."}, status=status.HTTP_400_BAD_REQUEST)


class SupportTicketsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.role in ADMIN_ROLES:
            qs = SupportTicket.objects.select_related("user").all()[:40]
        else:
            qs = SupportTicket.objects.filter(user=request.user)[:20]
        return Response(
            {
                "results": [
                    {
                        "id": str(t.id),
                        "ticket_number": t.ticket_number,
                        "user_name": t.user.full_name,
                        "category": t.category,
                        "subject": t.subject,
                        "status": t.status,
                        "sla_hours": t.sla_hours,
                        "messages": t.messages,
                        "created_at": t.created_at,
                    }
                    for t in qs
                ]
            }
        )

    def post(self, request):
        ticket_id = request.data.get("ticket_id")
        if ticket_id:
            t = SupportTicket.objects.filter(id=ticket_id).first()
            if not t:
                return Response({"detail": "Ticket topilmadi."}, status=status.HTTP_404_NOT_FOUND)
            if request.user.role not in ADMIN_ROLES and t.user_id != request.user.id:
                return Response({"detail": "Ruxsat yo‘q."}, status=status.HTTP_403_FORBIDDEN)
            reply = (request.data.get("message") or "").strip()
            if reply:
                t.messages = t.messages + [{"sender": request.user.full_name, "role": request.user.role, "text": reply, "at": timezone.now().isoformat()}]
            if request.data.get("status") and request.user.role in ADMIN_ROLES:
                t.status = request.data["status"]
            t.save()
            return Response({"ok": True})

        subject = (request.data.get("subject") or "").strip()
        msg = (request.data.get("message") or "").strip()
        if not subject or not msg:
            return Response({"detail": "Mavzu va xabar matni majburiy."}, status=status.HTTP_400_BAD_REQUEST)
        t = SupportTicket.objects.create(
            ticket_number=f"TKT-{uuid.uuid4().hex[:6].upper()}",
            user=request.user,
            category=request.data.get("category") or "GENERAL",
            subject=subject,
            messages=[{"sender": request.user.full_name, "role": request.user.role, "text": msg, "at": timezone.now().isoformat()}],
        )
        return Response({"ok": True, "ticket_id": str(t.id), "ticket_number": t.ticket_number}, status=status.HTTP_201_CREATED)
