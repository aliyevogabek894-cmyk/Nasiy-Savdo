"""Governance: BHM & Compliance Versions, Audit Logs, Security Events, Notifications, Privacy."""
import csv
import io
from django.http import HttpResponse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission, require_recent_mfa
from apps.accounts.models import MakerCheckerRequest
from apps.governance.models import (
    AuditLog,
    BhmValue,
    ComplianceRuleVersion,
    NotificationEvent,
    NotificationPreference,
    RetentionDeletionRequest,
    SecurityEvent,
)


class ComplianceSummaryView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        bhm = BhmValue.get_current_amount()
        rule = ComplianceRuleVersion.get_active()
        return Response(
            {
                "bhm_amount_uzs": bhm,
                "max_installment_uzs": bhm * rule.max_bhm_multiplier,
                "max_months": rule.max_months,
                "max_bhm_multiplier": rule.max_bhm_multiplier,
                "max_annual_extra_pct": rule.max_annual_extra_pct,
                "early_repayment_fee_pct": rule.early_repayment_fee_pct,
                "version_code": rule.version_code,
                "legal_basis_note": rule.legal_basis_note,
            }
        )


class BhmProposeUpdateView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "RISK_MANAGER", "FINANCE_OFFICER"}

    def post(self, request):
        if not require_recent_mfa(request):
            return Response({"detail": "BHM siyosatini o‘zgartirish uchun MFA tasdiqlash talab qilinadi."}, status=status.HTTP_403_FORBIDDEN)
        amount = int(request.data.get("amount_uzs") or 0)
        reason = (request.data.get("reason") or "").strip()
        if amount < 100000 or not reason:
            return Response({"detail": "Yaroqli BHM miqdori va sabab kiriting."}, status=status.HTTP_400_BAD_REQUEST)
        mc = MakerCheckerRequest.objects.create(
            action_type="BHM_UPDATE",
            target_model="BhmValue",
            payload={"amount_uzs": amount},
            reason=reason,
            requested_by=request.user,
        )
        AuditLog.record(actor=request.user, action="BHM_PROPOSED", object_type="MakerCheckerRequest", object_id=mc.id, reason=reason, after={"amount_uzs": amount})
        return Response({"ok": True, "request_id": str(mc.id), "message": "BHM o‘zgarishi Maker-Checker tasdig‘iga yuborildi."}, status=status.HTTP_201_CREATED)


class AuditLogListView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "AUDITOR", "FRAUD_ANALYST", "RISK_MANAGER"}

    def get(self, request):
        qs = AuditLog.objects.select_related("actor").all()[:100]
        return Response(
            {
                "results": [
                    {
                        "id": str(a.id),
                        "actor": a.actor.full_name if a.actor else "Tizim",
                        "actor_role": a.actor_role,
                        "action": a.action,
                        "object_type": a.object_type,
                        "object_id": a.object_id,
                        "reason": a.reason,
                        "correlation_id": a.correlation_id,
                        "ip_address": a.ip_address,
                        "created_at": a.created_at,
                    }
                    for a in qs
                ]
            }
        )


class SecurityEventListView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "AUDITOR", "FRAUD_ANALYST"}

    def get(self, request):
        events = SecurityEvent.objects.all()[:50]
        return Response(
            {
                "results": [
                    {
                        "id": str(e.id),
                        "event_type": e.event_type,
                        "severity": e.severity,
                        "description": e.description,
                        "ip_address": e.ip_address,
                        "resolved": e.resolved,
                        "created_at": e.created_at,
                    }
                    for e in events
                ]
            }
        )

    def post(self, request):
        event_id = request.data.get("event_id")
        ev = SecurityEvent.objects.filter(id=event_id).first()
        if not ev:
            return Response({"detail": "Hodisa topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        ev.resolved = True
        ev.resolved_by = request.user
        ev.save()
        AuditLog.record(actor=request.user, action="SECURITY_EVENT_RESOLVED", object_type="SecurityEvent", object_id=ev.id, reason="Xavfsizlik ogohlantirishi yopildi")
        return Response({"ok": True})


class NotificationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        items = NotificationEvent.objects.filter(user=request.user)[:30]
        return Response(
            {
                "preferences": {
                    "sms_transactional": pref.sms_transactional,
                    "telegram_alerts": pref.telegram_alerts,
                    "push_enabled": pref.push_enabled,
                    "marketing_opt_in": pref.marketing_opt_in,
                },
                "notifications": [
                    {
                        "id": str(n.id),
                        "channel": n.channel,
                        "category": n.category,
                        "status": n.status,
                        "title": n.title,
                        "body_masked": n.body_masked,
                        "created_at": n.created_at,
                    }
                    for n in items
                ],
            }
        )

    def patch(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        for field in ("sms_transactional", "telegram_alerts", "push_enabled", "marketing_opt_in"):
            if field in request.data:
                setattr(pref, field, bool(request.data[field]))
        pref.save()
        return Response({"ok": True})


class PrivacyRequestsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = RetentionDeletionRequest.objects.all() if request.user.role in ADMIN_ROLES else RetentionDeletionRequest.objects.filter(user=request.user)
        return Response(
            {
                "results": [
                    {
                        "id": str(r.id),
                        "user_name": r.user.full_name,
                        "request_type": r.request_type,
                        "reason": r.reason,
                        "status": r.status,
                        "created_at": r.created_at,
                    }
                    for r in qs[:30]
                ]
            }
        )

    def post(self, request):
        req_type = request.data.get("request_type")
        reason = (request.data.get("reason") or "").strip()
        if req_type not in {"EXPORT", "CORRECTION", "DELETION"}:
            return Response({"detail": "Noto‘g‘ri so‘rov turi."}, status=status.HTTP_400_BAD_REQUEST)
        obj = RetentionDeletionRequest.objects.create(user=request.user, request_type=req_type, reason=reason)
        AuditLog.record(actor=request.user, action="PRIVACY_REQUEST", object_type="RetentionDeletionRequest", object_id=obj.id, reason=reason)
        return Response({"ok": True, "id": str(obj.id)}, status=status.HTTP_201_CREATED)


class MaskedReportExportView(APIView):
    """Role-guarded CSV export excluding raw PII by default (Section 16 & 3.2)."""

    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "AUDITOR", "FINANCE_OFFICER", "FINANCE_OPERATIONS", "RISK_MANAGER"}

    def get(self, request):
        if not require_recent_mfa(request):
            return Response({"detail": "Ommaviy eksport uchun MFA tasdiqlash talab qilinadi (3.2)."}, status=status.HTTP_403_FORBIDDEN)
        from apps.finance.models import InstallmentContract
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["ContractNumber", "ProviderType", "PrincipalUZS", "MarkupUZS", "TotalPayableUZS", "RemainingUZS", "Months", "Status", "IsDemo"])
        for c in InstallmentContract.objects.all()[:500]:
            writer.writerow([c.contract_number, c.provider_type, c.principal_amount, c.markup_amount, c.total_payable, c.remaining_balance, c.months, c.status, c.is_demo])
        AuditLog.record(actor=request.user, action="REPORT_EXPORT", object_type="InstallmentContract", reason="Maxfiy shaxsiy ma'lumotsiz agregat eksport")
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="zarvon_nasiya_report_masked.csv"'
        return resp
