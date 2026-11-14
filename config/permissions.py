"""Role-Based Access Control (RBAC), Seller Tenant Isolation, and Object-Level Permissions."""
from rest_framework.permissions import BasePermission, SAFE_METHODS

ADMIN_ROLES = {
    "SUPER_ADMIN",
    "MARKETPLACE_ADMIN",
    "FINANCE_OFFICER",
    "RISK_MANAGER",
    "COLLECTIONS_AGENT",
    "FRAUD_ANALYST",
    "CONTENT_MANAGER",
    "DELIVERY_MANAGER",
    "FINANCE_OPERATIONS",
    "SUPPORT_AGENT",
    "AUDITOR",
}

SELLER_ROLES = {"SELLER_OWNER", "SELLER_STAFF"}


class HasRolePermission(BasePermission):
    """Require authenticated user whose role is in view.allowed_roles."""

    message = "Sizda ushbu bo‘limga kirish huquqi yo‘q (RBAC cheklovi)."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        allowed = getattr(view, "allowed_roles", None)
        if allowed is None:
            return True
        if user.role == "SUPER_ADMIN":
            return True
        if user.role == "AUDITOR" and request.method not in SAFE_METHODS:
            self.message = "Auditor faqat o‘qish va ruxsatli eksport huquqiga ega."
            return False
        return user.role in allowed


class ReadOnlyForAuditor(BasePermission):
    """Enforce strict read-only access for Auditor role."""

    message = "Auditor ma’lumotlarni tahrirlay olmaydi."

    def has_permission(self, request, view):
        user = request.user
        if user and user.is_authenticated and user.role == "AUDITOR":
            return request.method in SAFE_METHODS
        return True


class IsSellerTenantMember(BasePermission):
    """Ensure seller users only access resources belonging to their own store."""

    message = "Boshqa sotuvchi ma’lumotlariga kirish taqiqlangan (tenant izolyatsiyasi)."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role in {"SUPER_ADMIN", "MARKETPLACE_ADMIN"}:
            return True
        return user.role in SELLER_ROLES

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role in {"SUPER_ADMIN", "MARKETPLACE_ADMIN"}:
            return True
        store_id = getattr(obj, "store_id", None) or getattr(getattr(obj, "store", None), "id", None)
        if store_id is None and hasattr(obj, "id") and obj.__class__.__name__ == "Store":
            store_id = obj.id
        user_store_ids = set(user.get_accessible_store_ids())
        return store_id in user_store_ids


class IsCustomerOwner(BasePermission):
    """Ensure customers can only inspect/modify their own objects."""

    message = "Boshqa mijoz ma’lumotlariga kirish taqiqlangan."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role in ADMIN_ROLES:
            return True
        owner_id = getattr(obj, "user_id", None) or getattr(obj, "customer_id", None)
        return owner_id == user.id


def require_recent_mfa(request) -> bool:
    """
    Critical admin actions (role escalation, bank credentials, risk policy, bulk export)
    require MFA verification in current session or X-MFA-Code confirmation.
    """
    user = request.user
    if not user or not user.is_authenticated:
        return False
    if request.session.get("mfa_verified", False):
        return True
    mfa_header = request.headers.get("X-MFA-Code", "").strip()
    if mfa_header and len(mfa_header) == 6 and mfa_header.isdigit():
        request.session["mfa_verified"] = True
        return True
    return False
