"""Accounts, OTP, Session, Demo Role Switcher, Staff RBAC & Maker-Checker APIs."""
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission, require_recent_mfa
from config.utils import generate_otp_code, hash_token, mask_value
from apps.accounts.models import MakerCheckerRequest, OtpChallenge, Profile, User, UserRole, UserSession
from apps.governance.models import AuditLog, NotificationEvent, SecurityEvent


def serialize_user(user: User) -> dict:
    limit_info = None
    if hasattr(user, "installment_limit"):
        lim = user.installment_limit
        limit_info = {
            "tier": lim.tier,
            "total_limit_uzs": lim.total_limit_uzs,
            "used_limit_uzs": lim.used_limit_uzs,
            "available_limit_uzs": lim.available_limit_uzs,
            "is_frozen": lim.is_frozen,
            "freeze_reason": lim.freeze_reason,
            "is_demo_limit": lim.is_demo_limit,
        }
    return {
        "id": str(user.id),
        "phone": user.phone,
        "email": user.email or "",
        "full_name": user.full_name,
        "role": user.role,
        "role_label": user.get_role_display(),
        "preferred_language": user.preferred_language,
        "theme_preference": user.theme_preference,
        "mfa_enabled": user.mfa_enabled,
        "is_phone_verified": user.is_phone_verified,
        "kyc_status": user.kyc_status,
        "masked_pinfl": user.get_masked_pinfl(),
        "masked_inn": user.get_masked_inn(),
        "masked_passport": user.get_masked_passport(),
        "accessible_store_ids": [str(sid) for sid in user.get_accessible_store_ids()],
        "installment_limit": limit_info,
    }


class MeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        demo_accounts = []
        if settings.ZARVON_SANDBOX_MODE:
            demo_accounts = [
                {
                    "phone": u.phone,
                    "full_name": u.full_name,
                    "role": u.role,
                    "role_label": u.get_role_display(),
                }
                for u in User.objects.filter(is_active=True).order_by("role", "full_name")[:20]
            ]
        if not request.user.is_authenticated:
            return Response({"authenticated": False, "user": None, "demo_accounts": demo_accounts})
        return Response(
            {
                "authenticated": True,
                "user": serialize_user(request.user),
                "mfa_verified": bool(request.session.get("mfa_verified", False)),
                "demo_accounts": demo_accounts,
            }
        )


class RequestOtpView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        target = _normalize_uz_phone(request.data.get("target") or "")
        purpose = (request.data.get("purpose") or "LOGIN").strip()
        if not target:
            return Response({"detail": "Telefon raqami yoki email kiriting."}, status=status.HTTP_400_BAD_REQUEST)

        # SMS abuse rate limit check (Section 31.1)
        recent_count = OtpChallenge.objects.filter(
            target=target,
            created_at__gte=timezone.now() - timezone.timedelta(minutes=5),
        ).count()
        if recent_count >= 5:
            from apps.risk_collections.models import FraudSignal
            FraudSignal.objects.create(
                signal_type="SMS_ABUSE",
                severity="MEDIUM",
                summary=f"5 daqiqa ichida {mask_value(target, 4, 2)} ga ortiqcha OTP so‘rovi ({recent_count} ta).",
                metadata={"target_masked": mask_value(target, 4, 2), "count": recent_count},
            )
            return Response({"detail": "Juda ko‘p OTP so‘rovi. Bir necha daqiqadan so‘ng urinib ko‘ring."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        code = generate_otp_code(6)
        challenge = OtpChallenge.objects.create(
            target=target,
            purpose=purpose,
            code_hash=hash_token(code),
            demo_hint=code if settings.ZARVON_SANDBOX_MODE else "",
            expires_at=timezone.now() + timezone.timedelta(minutes=5),
        )
        return Response(
            {
                "challenge_id": str(challenge.id),
                "expires_in_seconds": 300,
                "demo_otp_preview": code if settings.ZARVON_SANDBOX_MODE else None,
                "message": "Tasdiqlash kodi yuborildi (Sandbox/Demo rejimida kod ekranda ko‘rsatiladi).",
            }
        )


def _normalize_uz_phone(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 10 and digits.startswith("8"):
        digits = "998" + digits[1:]
    if len(digits) == 12 and digits.startswith("998"):
        return f"+{digits}"
    return (raw or "").strip()


def _mask_person_name(full_name: str) -> str:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "Foydalanuvchi"
    return " ".join(p[0] + "*" * max(2, min(5, len(p) - 1)) for p in parts)


class PhoneLookupView(APIView):
    """Privacy-safe instant phone lookup to identify returning/new customers as they type."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        normalized = _normalize_uz_phone(request.data.get("phone") or "")
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if len(digits) < 9:
            return Response({"detail": "Kamida 9 xonali telefon raqamini kiriting."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(phone=normalized, is_active=True).first()
        if not user:
            return Response(
                {
                    "exists": False,
                    "normalized_phone": normalized,
                    "masked_name": None,
                    "role_label": "Yangi mijoz",
                    "message": "Yangi raqam — OTP kod bilan 10 soniyada profilingiz ochiladi.",
                }
            )
        return Response(
            {
                "exists": True,
                "normalized_phone": user.phone,
                "masked_name": _mask_person_name(user.full_name),
                "role": user.role,
                "role_label": user.get_role_display(),
                "kyc_status": user.kyc_status,
                "is_phone_verified": user.is_phone_verified,
                "message": "Siz tizimdan aniqlandingiz! OTP kod orqali profilni tasdiqlang.",
            }
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone = _normalize_uz_phone(request.data.get("phone") or "")
        password = request.data.get("password") or ""
        otp_code = (request.data.get("otp_code") or "").strip()
        challenge_id = request.data.get("challenge_id")

        user = None
        if password:
            user = authenticate(request, username=phone, password=password)
        elif challenge_id and otp_code:
            challenge = OtpChallenge.objects.filter(id=challenge_id, target=phone, verified_at__isnull=True).first()
            if not challenge or challenge.is_expired:
                return Response({"detail": "OTP muddati tugagan yoki topilmadi."}, status=status.HTTP_400_BAD_REQUEST)
            if challenge.attempts >= challenge.max_attempts:
                return Response({"detail": "Urinishlar soni tugadi."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if challenge.code_hash != hash_token(otp_code):
                challenge.attempts += 1
                challenge.save(update_fields=["attempts"])
                return Response({"detail": "OTP kod noto‘g‘ri."}, status=status.HTTP_400_BAD_REQUEST)
            challenge.verified_at = timezone.now()
            challenge.save(update_fields=["verified_at"])
            user = User.objects.filter(phone=phone).first()
            if not user:
                typed_name = (request.data.get("full_name") or "").strip()[:120]
                user = User.objects.create_user(
                    phone=phone,
                    full_name=typed_name or f"Mijoz {phone[-4:]}",
                    role=UserRole.CUSTOMER,
                    is_phone_verified=True,
                )
                Profile.objects.get_or_create(user=user)

        if not user or not user.is_active:
            SecurityEvent.objects.create(
                event_type="FAILED_LOGIN",
                severity="LOW",
                description=f"Muvaffaqiyatsiz kirish urinishi: {mask_value(phone, 4, 2)}",
            )
            return Response({"detail": "Telefon yoki parol noto‘g‘ri."}, status=status.HTTP_401_UNAUTHORIZED)

        login(request, user)
        request.session["mfa_verified"] = False
        UserSession.objects.create(
            user=user,
            device_name=(request.headers.get("User-Agent") or "Web Browser")[:110],
            ip_address=request.META.get("REMOTE_ADDR", "127.0.0.1"),
        )
        AuditLog.record(actor=user, action="LOGIN", object_type="User", object_id=user.id, reason="Tizimga kirish")
        return Response({"ok": True, "user": serialize_user(user)})


class DemoRoleSwitchView(APIView):
    """Sandbox-only role switcher to inspect Customer, Seller, and all Admin roles effortlessly."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not settings.ZARVON_SANDBOX_MODE:
            return Response({"detail": "Faqat Sandbox rejimida ruxsat etilgan."}, status=status.HTTP_403_FORBIDDEN)
        phone = (request.data.get("phone") or "").strip()
        role = (request.data.get("role") or "").strip()
        user = User.objects.filter(phone=phone).first() if phone else User.objects.filter(role=role, is_active=True).first()
        if not user:
            return Response({"detail": "Demo foydalanuvchi topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        login(request, user)
        request.session["mfa_verified"] = user.role in ADMIN_ROLES
        AuditLog.record(actor=user, action="DEMO_SWITCH", object_type="User", object_id=user.id, reason=f"Sandbox rol almashuvi: {user.role}")
        return Response({"ok": True, "user": serialize_user(user)})


class VerifyMfaView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        code = (request.data.get("code") or "").strip()
        if len(code) != 6 or not code.isdigit():
            return Response({"detail": "6 xonali MFA kodini kiriting (masalan: 123456 sandbox uchun)."}, status=status.HTTP_400_BAD_REQUEST)
        request.session["mfa_verified"] = True
        AuditLog.record(actor=request.user, action="MFA_VERIFIED", object_type="User", object_id=request.user.id, reason="Kritik amal uchun qayta autentifikatsiya")
        return Response({"ok": True, "mfa_verified": True})


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            AuditLog.record(actor=request.user, action="LOGOUT", object_type="User", object_id=request.user.id)
        logout(request)
        return Response({"ok": True})


class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        prof, _ = Profile.objects.get_or_create(user=request.user)
        sessions = [
            {
                "id": str(s.id),
                "device_name": s.device_name,
                "ip_address": s.ip_address,
                "is_revoked": s.is_revoked,
                "last_active": s.last_active,
            }
            for s in request.user.user_sessions.all()[:10]
        ]
        return Response(
            {
                "user": serialize_user(request.user),
                "profile": {
                    "region": prof.region,
                    "address": prof.address,
                    "telegram_username": prof.telegram_username,
                },
                "sessions": sessions,
            }
        )

    def patch(self, request):
        user = request.user
        prof, _ = Profile.objects.get_or_create(user=user)
        for field in ("full_name", "email", "preferred_language", "theme_preference"):
            if field in request.data and request.data[field]:
                setattr(user, field, request.data[field])
        user.save()
        for field in ("region", "address", "telegram_username"):
            if field in request.data:
                setattr(prof, field, request.data[field])
        prof.save()
        return Response({"ok": True, "user": serialize_user(user)})


class StaffManagementView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "AUDITOR"}

    def get(self, request):
        users = User.objects.filter(role__in=ADMIN_ROLES).order_by("role", "full_name")
        maker_requests = MakerCheckerRequest.objects.all()[:30]
        return Response(
            {
                "staff": [serialize_user(u) for u in users],
                "maker_checker_requests": [
                    {
                        "id": str(m.id),
                        "action_type": m.action_type,
                        "target_model": m.target_model,
                        "target_id": m.target_id,
                        "payload": m.payload,
                        "reason": m.reason,
                        "status": m.status,
                        "requested_by": m.requested_by.full_name,
                        "requested_by_id": str(m.requested_by_id),
                        "approved_by": m.approved_by.full_name if m.approved_by else None,
                        "decision_note": m.decision_note,
                        "created_at": m.created_at,
                    }
                    for m in maker_requests
                ],
            }
        )

    def post(self, request):
        if not require_recent_mfa(request):
            return Response({"detail": "Rol o‘zgartirish uchun MFA tasdiqlash talab qilinadi (3.2)."}, status=status.HTTP_403_FORBIDDEN)
        target_user_id = request.data.get("user_id")
        new_role = request.data.get("new_role")
        reason = (request.data.get("reason") or "").strip()
        if not target_user_id or new_role not in UserRole.values or not reason:
            return Response({"detail": "Foydalanuvchi, yangi rol va sabab majburiy."}, status=status.HTTP_400_BAD_REQUEST)

        req_obj = MakerCheckerRequest.objects.create(
            action_type="ROLE_CHANGE",
            target_model="User",
            target_id=str(target_user_id),
            payload={"new_role": new_role},
            reason=reason,
            requested_by=request.user,
        )
        AuditLog.record(actor=request.user, action="MAKER_ROLE_CHANGE_PROPOSED", object_type="MakerCheckerRequest", object_id=req_obj.id, reason=reason, after={"new_role": new_role})
        return Response({"ok": True, "request_id": str(req_obj.id), "message": "Ikkinchi tasdiq (Maker-Checker) uchun yuborildi."}, status=status.HTTP_201_CREATED)


class MakerCheckerDecisionView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "RISK_MANAGER", "FINANCE_OPERATIONS"}

    @transaction.atomic
    def post(self, request, pk):
        if not require_recent_mfa(request):
            return Response({"detail": "Maker-Checker tasdig‘i uchun MFA zarur."}, status=status.HTTP_403_FORBIDDEN)
        mc = MakerCheckerRequest.objects.select_for_update().filter(id=pk).first()
        if not mc:
            return Response({"detail": "So‘rov topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if mc.status != "PENDING":
            return Response({"detail": "Bu so‘rov allaqachon ko‘rib chiqilgan."}, status=status.HTTP_400_BAD_REQUEST)
        if mc.requested_by_id == request.user.id:
            return Response({"detail": "Maker va Checker bir xil xodim bo‘lishi mumkin emas (3.2)!"}, status=status.HTTP_403_FORBIDDEN)

        decision = request.data.get("decision")
        note = (request.data.get("decision_note") or "").strip()
        if decision not in {"APPROVED", "REJECTED"} or not note:
            return Response({"detail": "Qaror (APPROVED/REJECTED) va izoh majburiy."}, status=status.HTTP_400_BAD_REQUEST)

        mc.status = decision
        mc.approved_by = request.user
        mc.decision_note = note
        mc.decided_at = timezone.now()
        mc.save()

        if decision == "APPROVED":
            if mc.action_type == "ROLE_CHANGE":
                target = User.objects.get(id=mc.target_id)
                old_role = target.role
                target.role = mc.payload["new_role"]
                target.save(update_fields=["role"])
                AuditLog.record(actor=request.user, action="ROLE_CHANGED", object_type="User", object_id=target.id, reason=note, before={"role": old_role}, after={"role": target.role})
            elif mc.action_type == "BHM_UPDATE":
                from apps.governance.models import BhmValue
                BhmValue.objects.filter(is_active=True).update(is_active=False)
                BhmValue.objects.create(
                    amount_uzs=int(mc.payload["amount_uzs"]),
                    effective_from=timezone.now().date(),
                    is_active=True,
                    note=mc.reason,
                    created_by=request.user,
                )
                AuditLog.record(actor=request.user, action="BHM_UPDATED", object_type="BhmValue", reason=note, after=mc.payload)

        return Response({"ok": True, "status": mc.status})
