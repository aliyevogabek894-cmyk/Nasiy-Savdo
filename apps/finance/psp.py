"""Click Merchant API, Payme JSON-RPC 2.0, Paynet UWS & Uzum Payment Gateway Protocol Adapters."""
import base64
import hashlib
import hmac
import ipaddress
import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.commerce.models import Order, OrderStatus
from apps.finance.models import (
    ContractStatus,
    CustomerLimit,
    InstallmentContract,
    LimitEvent,
    PaymentRecord,
    PspTransaction,
    RepaymentEvent,
)
from apps.governance.models import AuditLog, NotificationEvent, SecurityEvent


def compute_click_signature(
    *,
    click_trans_id: str,
    service_id: str,
    secret_key: str,
    merchant_trans_id: str,
    amount: str,
    action: str,
    sign_time: str,
    merchant_prepare_id: str = "",
) -> str:
    """Official Click Prepare (action=0) / Complete (action=1) MD5 signature."""
    base = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}"
    if str(action) == "1":
        base += f"{merchant_prepare_id}"
    base += f"{amount}{action}{sign_time}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def verify_click_signature(params: dict) -> bool:
    secret = settings.CLICK_SECRET_KEY
    if not secret:
        return False
    expected = compute_click_signature(
        click_trans_id=str(params.get("click_trans_id", "")),
        service_id=str(params.get("service_id", "")),
        secret_key=secret,
        merchant_trans_id=str(params.get("merchant_trans_id", "")),
        merchant_prepare_id=str(params.get("merchant_prepare_id", "")),
        amount=str(params.get("amount", "")),
        action=str(params.get("action", "")),
        sign_time=str(params.get("sign_time", "")),
    )
    provided = str(params.get("sign_string", "")).lower().strip()
    return bool(provided) and hmac.compare_digest(expected.lower(), provided)


def get_client_ip(request) -> str:
    """Extract client IP respecting reverse proxies (Render / Nginx)."""
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()


def verify_psp_ip_allowlist(client_ip: str, allowed_csv: str) -> bool:
    """Check client IP against comma-separated IPs or CIDRs when allowlist is configured."""
    entries = [e.strip() for e in (allowed_csv or "").split(",") if e.strip()]
    if not entries:
        return True
    if not client_ip:
        return False
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for raw in entries:
        try:
            if "/" in raw:
                if ip_obj in ipaddress.ip_network(raw, strict=False):
                    return True
            elif ip_obj == ipaddress.ip_address(raw):
                return True
        except ValueError:
            continue
    return False


def verify_payme_auth(auth_header: str) -> bool:
    key = getattr(settings, "PAYME_CASHBOX_KEY", "") or getattr(settings, "PAYME_SECRET_KEY", "")
    if not key or not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
        login, pw = decoded.split(":", 1)
    except Exception:
        return False
    return hmac.compare_digest(login, "Paycom") and hmac.compare_digest(pw, key)


def verify_paynet_auth(auth_header: str) -> bool:
    """Validate Paynet UWS HTTP Basic Auth (`PAYNET_USERNAME:PAYNET_PASSWORD`)."""
    username = str(getattr(settings, "PAYNET_USERNAME", "") or "")
    password = str(getattr(settings, "PAYNET_PASSWORD", "") or "")
    service_id = str(getattr(settings, "PAYNET_SERVICE_ID", "") or "")
    if not password or not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
        login, pw = decoded.split(":", 1)
    except Exception:
        return False
    if not hmac.compare_digest(pw, password):
        return False
    return (bool(username) and hmac.compare_digest(login, username)) or (
        bool(service_id) and hmac.compare_digest(login, service_id)
    )


def resolve_payment_target(merchant_trans_id: str):
    """Find Order (ZRV-...) or InstallmentContract (NSY-...) by reference string."""
    ref = (merchant_trans_id or "").strip()
    order = Order.objects.filter(order_number=ref).first()
    if order:
        return "ORDER", order, int(order.total_amount)
    contract = InstallmentContract.objects.filter(contract_number=ref).first()
    if contract:
        next_item = contract.schedule_items.filter(status__in=["OVERDUE", "PARTIAL", "UPCOMING"]).order_by("installment_no").first()
        expected = int((next_item.amount_due + next_item.penalty_amount) - next_item.amount_paid) if next_item else int(contract.remaining_balance)
        return "CONTRACT", contract, max(0, expected)
    return None, None, 0


@transaction.atomic
def settle_psp_payment(*, psp_provider: str, target_kind: str, target_obj, amount_uzs: int, idem_key: str, external_trans_id: str):
    """Idempotently mark Order confirmed/paid OR settle InstallmentContract schedule via PSP."""
    if target_kind == "ORDER":
        order = Order.objects.select_for_update().get(id=target_obj.id)
        pay_rec, _ = PaymentRecord.objects.get_or_create(
            payment_intent_id=external_trans_id,
            defaults={
                "provider": psp_provider,
                "user": order.customer,
                "order": order,
                "amount": amount_uzs,
                "status": "SUCCEEDED",
                "reconciliation_ref": f"REC-{order.order_number}",
                "is_demo": settings.ZARVON_SANDBOX_MODE,
            },
        )
        if order.status in {OrderStatus.AWAITING_FINANCE, OrderStatus.PENDING}:
            order.status = OrderStatus.CONFIRMED
            order.save(update_fields=["status"])
            order.seller_orders.update(status=OrderStatus.CONFIRMED)
        return {"target": order.order_number, "settled_uzs": amount_uzs, "payment_id": str(pay_rec.id)}

    if target_kind == "CONTRACT":
        contract = InstallmentContract.objects.select_for_update().get(id=target_obj.id)
        existing_rec = PaymentRecord.objects.filter(payment_intent_id=external_trans_id).first()
        if RepaymentEvent.objects.filter(idempotency_key=idem_key).exists():
            return {
                "target": contract.contract_number,
                "idempotent_replay": True,
                "remaining_balance": contract.remaining_balance,
                "payment_id": str(existing_rec.id) if existing_rec else None,
            }
        applied = min(int(amount_uzs), contract.remaining_balance)
        if applied <= 0:
            return {"target": contract.contract_number, "remaining_balance": contract.remaining_balance, "payment_id": None}
        contract.remaining_balance -= applied
        left = applied
        for item in contract.schedule_items.filter(status__in=["OVERDUE", "PARTIAL", "UPCOMING"]).order_by("installment_no"):
            if left <= 0:
                break
            due_left = max(0, (item.amount_due + item.penalty_amount) - item.amount_paid)
            pay_here = min(left, due_left)
            item.amount_paid += pay_here
            left -= pay_here
            if item.amount_paid >= item.amount_due + item.penalty_amount:
                item.status = "PAID"
                item.paid_at = timezone.now()
            elif item.amount_paid > 0:
                item.status = "PARTIAL"
            item.save()
        if contract.remaining_balance == 0:
            contract.status = ContractStatus.CLOSED
            lim = CustomerLimit.objects.filter(user=contract.customer).first()
            if lim:
                restore = min(lim.used_limit_uzs, contract.principal_amount)
                lim.used_limit_uzs -= restore
                lim.save()
                LimitEvent.objects.create(customer_limit=lim, event_type="RESTORE", amount_delta=restore, reason=f"{psp_provider} orqali shartnoma #{contract.contract_number} yopildi")
        elif contract.status == ContractStatus.OVERDUE and not contract.schedule_items.filter(status="OVERDUE").exists():
            contract.status = ContractStatus.ACTIVE
        contract.save()
        RepaymentEvent.objects.create(
            contract=contract,
            amount=applied,
            payment_method=psp_provider,
            is_early_repayment=False,
            early_fee=0,
            idempotency_key=idem_key,
        )
        pay_rec, _ = PaymentRecord.objects.get_or_create(
            payment_intent_id=external_trans_id,
            defaults={
                "provider": psp_provider,
                "user": contract.customer,
                "contract": contract,
                "amount": applied,
                "status": "SUCCEEDED",
                "reconciliation_ref": f"REC-{contract.contract_number}",
                "is_demo": settings.ZARVON_SANDBOX_MODE,
            },
        )
        NotificationEvent.objects.create(
            user=contract.customer,
            channel="TELEGRAM",
            category="TRANSACTIONAL",
            status="delivered",
            title=f"{psp_provider} orqali to‘lov qabul qilindi ({applied:,} so‘m)",
            body_masked=f"Shartnoma #{contract.contract_number} bo‘yicha qoldiq: {contract.remaining_balance:,} so‘m.",
        )
        return {
            "target": contract.contract_number,
            "settled_uzs": applied,
            "remaining_balance": contract.remaining_balance,
            "contract_status": contract.status,
            "payment_id": str(pay_rec.id),
        }
    return {}


@transaction.atomic
def process_click_webhook(params: dict, *, skip_sig_for_trusted_sandbox: bool = False) -> dict:
    """Handle Click Prepare (action=0) and Complete (action=1)."""
    sig_ok = True if skip_sig_for_trusted_sandbox else verify_click_signature(params)
    click_trans_id = str(params.get("click_trans_id") or "")
    merchant_trans_id = str(params.get("merchant_trans_id") or "")
    action = str(params.get("action") or "")

    if not sig_ok:
        SecurityEvent.objects.create(
            event_type="INVALID_CLICK_SIGNATURE",
            severity="HIGH",
            description=f"Click webhook imzosi mos kelmadi ({merchant_trans_id}).",
            details={"click_trans_id": click_trans_id, "merchant_trans_id": merchant_trans_id},
        )
        return {"error": -1, "error_note": "SIGN CHECK FAILED!"}

    target_kind, target_obj, expected_uzs = resolve_payment_target(merchant_trans_id)
    if not target_obj:
        return {"error": -5, "error_note": "Order or contract does not exist"}

    try:
        amount_uzs = int(float(params.get("amount") or 0))
    except (TypeError, ValueError):
        return {"error": -2, "error_note": "Incorrect parameter amount"}

    if target_kind == "ORDER" and amount_uzs != expected_uzs:
        return {"error": -2, "error_note": "Incorrect parameter amount"}
    if target_kind == "CONTRACT":
        if target_obj.remaining_balance <= 0 or target_obj.status in {ContractStatus.CLOSED, ContractStatus.CANCELLED}:
            return {"error": -4, "error_note": "Already paid"}
        if amount_uzs > target_obj.remaining_balance:
            return {"error": -2, "error_note": "Incorrect parameter amount"}
    if amount_uzs <= 0:
        return {"error": -2, "error_note": "Incorrect parameter amount"}

    if action == "0":
        tx, created = PspTransaction.objects.get_or_create(
            idempotency_key=f"click-prep-{click_trans_id}",
            defaults={
                "psp_provider": "Click",
                "external_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "merchant_prepare_id": f"PREP-{uuid.uuid4().hex[:8].upper()}",
                "action_stage": "PREPARED",
                "amount_tiyin": amount_uzs * 100,
                "state_code": 1,
                "signature_verified": sig_ok,
                "order": target_obj if target_kind == "ORDER" else None,
                "contract": target_obj if target_kind == "CONTRACT" else None,
                "raw_payload_sanitized": {"action": "0", "merchant_trans_id": merchant_trans_id, "amount": amount_uzs},
                "is_demo": settings.ZARVON_SANDBOX_MODE,
            },
        )
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_prepare_id": tx.merchant_prepare_id,
            "error": 0,
            "error_note": "Success",
        }

    if action == "1":
        prep_id = str(params.get("merchant_prepare_id") or "")
        tx = PspTransaction.objects.select_for_update().filter(psp_provider="Click", merchant_prepare_id=prep_id, merchant_trans_id=merchant_trans_id).first()
        if not tx:
            return {"error": -6, "error_note": "Transaction does not exist"}
        try:
            incoming_err = int(params.get("error") or 0)
        except (TypeError, ValueError):
            incoming_err = 0
        if incoming_err < 0:
            tx.action_stage = "CANCELLED"
            tx.state_code = -2
            raw = dict(tx.raw_payload_sanitized or {})
            raw["click_cancel_error"] = incoming_err
            tx.raw_payload_sanitized = raw
            tx.save(update_fields=["action_stage", "state_code", "raw_payload_sanitized", "updated_at"])
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": tx.merchant_prepare_id,
                "error": -9,
                "error_note": "Transaction cancelled",
            }
        if tx.action_stage == "CANCELLED":
            return {"error": -9, "error_note": "Transaction cancelled"}
        if tx.action_stage == "PERFORMED":
            return {
                "click_trans_id": click_trans_id,
                "merchant_trans_id": merchant_trans_id,
                "merchant_confirm_id": tx.merchant_prepare_id,
                "error": -4,
                "error_note": "Already paid",
            }
        tx.action_stage = "PERFORMED"
        tx.state_code = 2
        tx.save(update_fields=["action_stage", "state_code", "updated_at"])
        settled = settle_psp_payment(
            psp_provider="Click",
            target_kind=target_kind,
            target_obj=target_obj,
            amount_uzs=amount_uzs,
            idem_key=f"click-complete-{click_trans_id}",
            external_trans_id=f"CLK-{click_trans_id}",
        )
        return {
            "click_trans_id": click_trans_id,
            "merchant_trans_id": merchant_trans_id,
            "merchant_confirm_id": tx.merchant_prepare_id,
            "payment_id": settled.get("payment_id"),
            "error": 0,
            "error_note": "Success",
        }

    return {"error": -3, "error_note": "Action not found"}


@transaction.atomic
def process_payme_rpc(payload: dict, auth_header: str, *, skip_auth_for_trusted_sandbox: bool = False) -> dict:
    """Handle Payme JSON-RPC 2.0 Merchant API protocol cleanly."""
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if not skip_auth_for_trusted_sandbox and not verify_payme_auth(auth_header):
        SecurityEvent.objects.create(
            event_type="INVALID_PAYME_AUTH",
            severity="HIGH",
            description=f"Payme Basic Auth rad etildi ({method}).",
        )
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32504, "message": "Insufficient privilege to perform this method"}}

    if method == "CheckPerformTransaction":
        ref = str((params.get("account") or {}).get("order_id") or (params.get("account") or {}).get("contract_id") or "")
        amount_tiyin = int(params.get("amount") or 0)
        kind, obj, expected_uzs = resolve_payment_target(ref)
        if not obj:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31050, "message": {"uz": "Buyurtma yoki shartnoma topilmadi", "en": "Order not found"}}}
        if kind == "ORDER" and amount_tiyin != expected_uzs * 100 or amount_tiyin <= 0:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31001, "message": {"uz": "Summa noto‘g‘ri", "en": "Invalid amount"}}}
        if kind == "CONTRACT":
            if obj.remaining_balance <= 0 or obj.status in {ContractStatus.CLOSED, ContractStatus.CANCELLED}:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31051, "message": {"uz": "Shartnoma qarzi allaqachon yopilgan", "en": "Already paid"}}}
            if amount_tiyin > obj.remaining_balance * 100:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31001, "message": {"uz": "Summa qarz qoldig‘idan oshib ketdi", "en": "Amount exceeds balance"}}}
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"allow": True}}

    if method == "CreateTransaction":
        payme_id = str(params.get("id") or "")
        ref = str((params.get("account") or {}).get("order_id") or (params.get("account") or {}).get("contract_id") or "")
        amount_tiyin = int(params.get("amount") or 0)
        existing_tx = PspTransaction.objects.select_for_update().filter(psp_provider="Payme", external_trans_id=payme_id).first()
        if existing_tx:
            if existing_tx.state_code != 1:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31008, "message": "Transaction state does not allow CreateTransaction"}}
            if existing_tx.amount_tiyin != amount_tiyin:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31001, "message": "Invalid amount"}}
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "create_time": int(existing_tx.created_at.timestamp() * 1000),
                    "transaction": str(existing_tx.id),
                    "state": existing_tx.state_code,
                },
            }

        kind, obj, expected_uzs = resolve_payment_target(ref)
        if not obj:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31050, "message": "Order/Contract not found"}}
        if kind == "ORDER" and amount_tiyin != expected_uzs * 100 or amount_tiyin <= 0:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31001, "message": "Invalid amount"}}
        if kind == "CONTRACT":
            if obj.remaining_balance <= 0 or obj.status in {ContractStatus.CLOSED, ContractStatus.CANCELLED}:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31051, "message": "Contract already closed"}}
            if amount_tiyin > obj.remaining_balance * 100:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31001, "message": "Amount exceeds balance"}}

        tx, _ = PspTransaction.objects.get_or_create(
            idempotency_key=f"payme-{payme_id}",
            defaults={
                "psp_provider": "Payme",
                "external_trans_id": payme_id,
                "merchant_trans_id": ref,
                "action_stage": "PREPARED",
                "amount_tiyin": amount_tiyin,
                "state_code": 1,
                "signature_verified": True,
                "order": obj if kind == "ORDER" else None,
                "contract": obj if kind == "CONTRACT" else None,
                "raw_payload_sanitized": {"method": method, "ref": ref, "amount_tiyin": amount_tiyin},
                "is_demo": settings.ZARVON_SANDBOX_MODE,
            },
        )
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "create_time": int(tx.created_at.timestamp() * 1000),
                "transaction": str(tx.id),
                "state": tx.state_code,
            },
        }

    if method == "PerformTransaction":
        payme_id = str(params.get("id") or "")
        tx = PspTransaction.objects.select_for_update().filter(psp_provider="Payme", external_trans_id=payme_id).first()
        if not tx:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31003, "message": "Transaction not found"}}
        if tx.state_code < 0:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31008, "message": "Cancelled transaction cannot be performed"}}
        if tx.state_code == 2:
            raw = tx.raw_payload_sanitized or {}
            perf_ms = int(raw.get("perform_time_ms") or tx.updated_at.timestamp() * 1000)
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"transaction": str(tx.id), "perform_time": perf_ms, "state": 2}}
        perf_ms = int(timezone.now().timestamp() * 1000)
        tx.action_stage = "PERFORMED"
        tx.state_code = 2
        raw = dict(tx.raw_payload_sanitized or {})
        raw["perform_time_ms"] = perf_ms
        tx.raw_payload_sanitized = raw
        tx.save(update_fields=["action_stage", "state_code", "raw_payload_sanitized", "updated_at"])
        kind, obj, _ = resolve_payment_target(tx.merchant_trans_id)
        if obj:
            settle_psp_payment(
                psp_provider="Payme",
                target_kind=kind,
                target_obj=obj,
                amount_uzs=tx.amount_tiyin // 100,
                idem_key=f"payme-perf-{payme_id}",
                external_trans_id=f"PAYME-{payme_id}",
            )
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "transaction": str(tx.id),
                "perform_time": perf_ms,
                "state": 2,
            },
        }

    if method == "CancelTransaction":
        payme_id = str(params.get("id") or "")
        tx = PspTransaction.objects.select_for_update().filter(psp_provider="Payme", external_trans_id=payme_id).first()
        if not tx:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31003, "message": "Transaction not found"}}
        raw = dict(tx.raw_payload_sanitized or {})
        if tx.state_code in (-1, -2):
            cancel_ms = int(raw.get("cancel_time_ms") or tx.updated_at.timestamp() * 1000)
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"transaction": str(tx.id), "cancel_time": cancel_ms, "state": tx.state_code}}
        cancel_ms = int(timezone.now().timestamp() * 1000)
        tx.action_stage = "CANCELLED"
        tx.state_code = -2 if tx.state_code == 2 else -1
        raw["cancel_time_ms"] = cancel_ms
        if params.get("reason") is not None:
            raw["cancel_reason"] = params.get("reason")
        tx.raw_payload_sanitized = raw
        tx.save(update_fields=["action_stage", "state_code", "raw_payload_sanitized", "updated_at"])
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"transaction": str(tx.id), "cancel_time": cancel_ms, "state": tx.state_code}}

    if method == "CheckTransaction":
        payme_id = str(params.get("id") or "")
        tx = PspTransaction.objects.filter(psp_provider="Payme", external_trans_id=payme_id).first()
        if not tx:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31003, "message": "Transaction not found"}}
        raw = tx.raw_payload_sanitized or {}
        perform_ms = int(raw.get("perform_time_ms") or (tx.updated_at.timestamp() * 1000 if tx.state_code in (2, -2) else 0))
        cancel_ms = int(raw.get("cancel_time_ms") or (tx.updated_at.timestamp() * 1000 if tx.state_code < 0 else 0))
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "create_time": int(tx.created_at.timestamp() * 1000),
                "perform_time": perform_ms if tx.state_code in (2, -2) else 0,
                "cancel_time": cancel_ms if tx.state_code < 0 else 0,
                "transaction": str(tx.id),
                "state": tx.state_code,
                "reason": raw.get("cancel_reason"),
            },
        }

    if method == "GetStatement":
        txs = PspTransaction.objects.filter(psp_provider="Payme").order_by("-created_at")[:50]
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "transactions": [
                    {"id": t.external_trans_id, "amount": t.amount_tiyin, "account": {"order_id": t.merchant_trans_id}, "state": t.state_code, "create_time": int(t.created_at.timestamp() * 1000)}
                    for t in txs
                ]
            },
        }

    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}


# --- Uzum Bank Merchant API & Unified Checkout Link Generator ---
import base64 as _psp_base64
import hashlib as _psp_hashlib
import hmac as _psp_hmac
from urllib.parse import urlencode as _psp_urlencode
from django.conf import settings as _psp_settings
from django.db import transaction as _psp_transaction
from django.utils import timezone as _psp_timezone
from apps.finance.models import PspTransaction as _PspTransaction
from apps.governance.models import SecurityEvent as _SecurityEvent


def build_psp_checkout_payload(*, psp_provider: str, reference: str, amount_uzs: int) -> dict:
    """Build official Payme / Click / Uzum Bank / Paynet checkout redirect URLs & deep-links."""
    amt_uzs = max(1000, int(amount_uzs or 0))
    amt_tiyin = amt_uzs * 100
    sandbox = bool(getattr(_psp_settings, "ZARVON_SANDBOX_MODE", True))

    payme_mid = getattr(_psp_settings, "PAYME_MERCHANT_ID", "") or "65f9a8e10000000000000001"
    payme_raw = f"m={payme_mid};ac.order_id={reference};a={amt_tiyin}"
    payme_b64 = _psp_base64.b64encode(payme_raw.encode("utf-8")).decode("ascii")
    payme_host = "test.paycom.uz" if sandbox else "checkout.paycom.uz"
    payme_url = f"https://{payme_host}/{payme_b64}"

    click_params = _psp_urlencode(
        {
            "service_id": getattr(_psp_settings, "CLICK_SERVICE_ID", "38491"),
            "merchant_id": getattr(_psp_settings, "CLICK_MERCHANT_ID", "24810"),
            "amount": f"{amt_uzs:.2f}",
            "transaction_param": reference,
        }
    )
    click_url = f"https://my.click.uz/services/pay?{click_params}"

    uzum_service = getattr(_psp_settings, "UZUM_SERVICE_ID", "49210")
    uzum_params = _psp_urlencode({"serviceId": uzum_service, "orderId": reference, "amount": amt_tiyin})
    uzum_url = f"https://www.apelsin.uz/open-service?{uzum_params}"

    paynet_url = f"https://paynet.uz/payment?merchant=zarvon&account={reference}&amount={amt_uzs}"

    provider_map = {
        "Payme": payme_url,
        "Click": click_url,
        "Uzum Bank": uzum_url,
        "Paynet": paynet_url,
    }
    selected_url = provider_map.get(psp_provider, payme_url)
    return {
        "psp_provider": psp_provider,
        "reference": reference,
        "amount_uzs": amt_uzs,
        "amount_tiyin": amt_tiyin,
        "mode": "SANDBOX" if sandbox else "PRODUCTION",
        "checkout_url": selected_url,
        "links": {
            "payme": payme_url,
            "click": click_url,
            "uzum_bank": uzum_url,
            "paynet": paynet_url,
        },
        "protocol": (
            "Uzum Merchant REST (/check -> /create -> /confirm, tiyin)"
            if psp_provider == "Uzum Bank"
            else "JSON-RPC 2.0 (Base64 checkout.paycom.uz)"
            if psp_provider == "Payme"
            else "Click Prepare/Complete MD5"
            if psp_provider == "Click"
            else "Paynet UWS JSON-RPC (GetInformation -> PerformTransaction -> CheckTransaction)"
            if psp_provider == "Paynet"
            else "Token/Gateway"
        ),
    }


def _uzum_now_ms() -> int:
    return int(_psp_timezone.now().timestamp() * 1000)


def verify_uzum_auth(auth_header: str, signature_header: str = "", body_raw: str = "") -> bool:
    """Validate Uzum Bank Basic auth (`Basic base64(serviceId:secretKey)`) or HMAC-SHA256 X-Signature."""
    secret = getattr(_psp_settings, "UZUM_SECRET_KEY", "") or ""
    service_id = str(getattr(_psp_settings, "UZUM_SERVICE_ID", "") or "")
    if not secret:
        return False

    if auth_header and auth_header.startswith("Basic "):
        try:
            decoded = _psp_base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            user_part, _, pass_part = decoded.partition(":")
            if _psp_hmac.compare_digest(pass_part, secret) and (not service_id or _psp_hmac.compare_digest(user_part, service_id)):
                return True
        except Exception:
            pass

    if signature_header and body_raw is not None:
        digest = _psp_hmac.new(secret.encode("utf-8"), body_raw.encode("utf-8"), _psp_hashlib.sha256).hexdigest()
        if _psp_hmac.compare_digest(signature_header.strip().lower(), digest.lower()):
            return True

    return False


def _uzum_err(code: str, message: str, service_id: str = "") -> dict:
    return {
        "serviceId": str(service_id or getattr(_psp_settings, "UZUM_SERVICE_ID", "49210")),
        "timestamp": _uzum_now_ms(),
        "status": "FAILED",
        "errorCode": code,
        "errorMessage": message,
    }


def process_uzum_webhook(
    stage: str,
    payload: dict,
    auth_header: str = "",
    signature_header: str = "",
    body_raw: str = "",
) -> dict:
    """Official Uzum Bank Merchant API state machine (`check`, `create`, `confirm`, `reverse`, `status`)."""
    service_id = str(payload.get("serviceId") or getattr(_psp_settings, "UZUM_SERVICE_ID", "49210"))
    if not verify_uzum_auth(auth_header, signature_header=signature_header, body_raw=body_raw):
        _SecurityEvent.objects.create(
            event_type="PSP_UZUM_AUTH_FAILED",
            severity="HIGH",
            description="Uzum Bank webhook autentifikatsiya xatosi (Basic/HMAC imzo mos emas).",
            details={"stage": stage, "serviceId": service_id},
        )
        return _uzum_err("10001", "Unauthorized merchant signature", service_id)

    params = payload.get("params") or {}
    reference = str(params.get("orderId") or params.get("account") or payload.get("orderId") or "").strip()
    trans_id = str(payload.get("transId") or "").strip()
    try:
        amount_tiyin = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount_tiyin = 0

    stage_norm = (stage or payload.get("action") or "check").strip().lower()

    if stage_norm == "check":
        target_kind, target_obj, expected_uzs = resolve_payment_target(reference)
        if not target_obj:
            return _uzum_err("10007", "Buyurtma yoki shartnoma topilmadi", service_id)
        return {
            "serviceId": service_id,
            "timestamp": _uzum_now_ms(),
            "status": "OK",
            "data": {
                "account": {"value": reference},
                "expected_amount_tiyin": int(expected_uzs * 100),
            },
        }

    with _psp_transaction.atomic():
        if stage_norm == "create":
            target_kind, target_obj, expected_uzs = resolve_payment_target(reference)
            if not target_obj:
                return _uzum_err("10007", "Buyurtma topilmadi", service_id)
            order = target_obj if target_kind == "ORDER" else None
            contract = target_obj if target_kind == "CONTRACT" else None
            if amount_tiyin <= 0 or (target_kind == "ORDER" and expected_uzs > 0 and amount_tiyin != expected_uzs * 100):
                return _uzum_err("10011", "Summa mos emas (tiyin)", service_id)
            if not trans_id:
                trans_id = f"uzm-{_uzum_now_ms()}"
            existing = _PspTransaction.objects.select_for_update().filter(
                psp_provider="Uzum Bank", external_trans_id=trans_id
            ).first()
            if existing:
                return {
                    "serviceId": service_id,
                    "transId": existing.external_trans_id,
                    "status": "CREATED",
                    "transTime": _uzum_now_ms(),
                    "amount": existing.amount_tiyin,
                }
            tx = _PspTransaction.objects.create(
                psp_provider="Uzum Bank",
                external_trans_id=trans_id,
                merchant_trans_id=reference,
                action_stage="PREPARED",
                amount_tiyin=amount_tiyin,
                state_code=1,
                signature_verified=True,
                idempotency_key=f"uzum-{trans_id}",
                order=order,
                contract=contract,
                raw_payload_sanitized={"stage": "create", "reference": reference, "amount_tiyin": amount_tiyin},
                is_demo=bool(getattr(_psp_settings, "ZARVON_SANDBOX_MODE", True)),
            )
            return {
                "serviceId": service_id,
                "transId": tx.external_trans_id,
                "status": "CREATED",
                "transTime": _uzum_now_ms(),
                "amount": tx.amount_tiyin,
            }

        tx = _PspTransaction.objects.select_for_update().filter(
            psp_provider="Uzum Bank", external_trans_id=trans_id
        ).first()
        if not tx:
            return _uzum_err("10014", "Tranzaksiya topilmadi", service_id)

        if stage_norm == "confirm":
            if tx.state_code == -1:
                return _uzum_err("10015", "Bekor qilingan tranzaksiyani tasdiqlab bo‘lmaydi", service_id)
            if tx.state_code == 2:
                return {
                    "serviceId": service_id,
                    "transId": tx.external_trans_id,
                    "status": "CONFIRMED",
                    "confirmTime": _uzum_now_ms(),
                    "amount": tx.amount_tiyin,
                }
            tx.state_code = 2
            tx.action_stage = "PERFORMED"
            tx.save(update_fields=["state_code", "action_stage", "updated_at"])
            t_kind = "ORDER" if tx.order_id else "CONTRACT"
            t_obj = tx.order or tx.contract
            if t_obj:
                settle_psp_payment(
                    psp_provider="Uzum Bank",
                    target_kind=t_kind,
                    target_obj=t_obj,
                    amount_uzs=tx.amount_tiyin // 100,
                    idem_key=f"uzum-settle-{tx.external_trans_id}",
                    external_trans_id=tx.external_trans_id,
                )
            return {
                "serviceId": service_id,
                "transId": tx.external_trans_id,
                "status": "CONFIRMED",
                "confirmTime": _uzum_now_ms(),
                "amount": tx.amount_tiyin,
            }

        if stage_norm == "reverse":
            tx.state_code = -1
            tx.action_stage = "CANCELLED"
            tx.save(update_fields=["state_code", "action_stage", "updated_at"])
            return {
                "serviceId": service_id,
                "transId": tx.external_trans_id,
                "status": "REVERSED",
                "reverseTime": _uzum_now_ms(),
                "amount": tx.amount_tiyin,
            }

        if stage_norm == "status":
            status_map = {1: "CREATED", 2: "CONFIRMED", -1: "REVERSED", -2: "REVERSED"}
            return {
                "serviceId": service_id,
                "transId": tx.external_trans_id,
                "status": status_map.get(tx.state_code, "FAILED"),
                "amount": tx.amount_tiyin,
            }

    return _uzum_err("10002", f"Noma’lum Uzum Bank bosqichi: {stage_norm}", service_id)


# --- Paynet UWS JSON-RPC Protocol Adapter ---
from config.utils import mask_value as _mask_value


def _paynet_err(rpc_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }


def _extract_paynet_ref(params: dict) -> str:
    fields = params.get("fields") or {}
    return str(
        fields.get("order_id")
        or fields.get("contract_id")
        or fields.get("account")
        or params.get("account")
        or params.get("orderId")
        or params.get("contract_id")
        or ""
    ).strip()


@transaction.atomic
def process_paynet_uws(
    payload: dict,
    auth_header: str = "",
    *,
    client_ip: str = "",
    skip_auth_for_trusted_sandbox: bool = False,
) -> tuple[dict, int]:
    """Paynet UWS JSON-RPC handler (`GetInformation`, `PerformTransaction`, `CheckTransaction`, `CancelTransaction`, `GetStatement`)."""
    rpc_id = payload.get("id")
    method = str(payload.get("method") or "").strip()
    params = payload.get("params") or {}

    if not skip_auth_for_trusted_sandbox:
        allowed_ips = getattr(settings, "PAYNET_ALLOWED_IPS", "")
        if not verify_psp_ip_allowlist(client_ip, allowed_ips):
            SecurityEvent.objects.create(
                event_type="PAYNET_IP_BLOCKED",
                severity="HIGH",
                ip_address=client_ip or "unknown",
                description=f"Ruxsat etilmagan IP manzildan Paynet UWS so‘rovi rad etildi ({method}).",
            )
            return _paynet_err(rpc_id, 403, "IP address not allowed"), 403
        if not verify_paynet_auth(auth_header):
            SecurityEvent.objects.create(
                event_type="INVALID_PAYNET_AUTH",
                severity="HIGH",
                ip_address=client_ip or "unknown",
                description=f"Paynet UWS Basic Auth rad etildi ({method}).",
            )
            return _paynet_err(rpc_id, 103, "Unauthorized Paynet UWS credentials"), 401

    now_iso = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

    if method == "GetInformation":
        ref = _extract_paynet_ref(params)
        kind, obj, expected_uzs = resolve_payment_target(ref)
        if not obj:
            return _paynet_err(rpc_id, 302, "Buyurtma yoki nasiya shartnomasi topilmadi"), 200
        cust_name = _mask_value(obj.customer.full_name, 2, 1)
        bal_uzs = expected_uzs if kind == "ORDER" else int(obj.remaining_balance)
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "status": 0,
                "timeStamp": now_iso,
                "fields": {
                    "account": ref,
                    "target_type": kind,
                    "fio": cust_name,
                    "expected_amount_uzs": int(expected_uzs),
                    "expected_amount_tiyin": int(expected_uzs * 100),
                    "remaining_debt_uzs": int(bal_uzs),
                },
            },
        }, 200

    if method == "PerformTransaction":
        tx_id = str(params.get("transactionId") or params.get("id") or "").strip()
        ref = _extract_paynet_ref(params)
        try:
            amount_tiyin = int(params.get("amount") or 0)
        except (TypeError, ValueError):
            amount_tiyin = 0
        if not tx_id:
            return _paynet_err(rpc_id, 411, "transactionId majburiy"), 200

        existing = PspTransaction.objects.select_for_update().filter(
            psp_provider="Paynet", external_trans_id=tx_id
        ).first()
        if existing:
            if existing.action_stage == "CANCELLED":
                return _paynet_err(rpc_id, 202, "Tranzaksiya bekor qilingan"), 200
            pay_rec = PaymentRecord.objects.filter(payment_intent_id=f"PAYNET-{tx_id}").first()
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "status": 0,
                    "timeStamp": now_iso,
                    "providerTrnId": str(existing.id),
                    "idempotent_replay": True,
                    "payment_id": str(pay_rec.id) if pay_rec else None,
                },
            }, 200

        kind, obj, expected_uzs = resolve_payment_target(ref)
        if not obj:
            return _paynet_err(rpc_id, 302, "Buyurtma yoki nasiya shartnomasi topilmadi"), 200
        if amount_tiyin <= 0 or amount_tiyin % 100 != 0:
            # Accept clean integer sum in tiyin; fallback check strictly positive
            if amount_tiyin <= 0:
                return _paynet_err(rpc_id, 411, "Summa noto‘g‘ri"), 200
        amount_uzs = amount_tiyin // 100
        if amount_uzs <= 0:
            return _paynet_err(rpc_id, 411, "Summa kamida 1 so‘m bo‘lishi kerak"), 200
        if kind == "ORDER" and amount_uzs != expected_uzs:
            return _paynet_err(rpc_id, 411, "Buyurtma summasi mos kelmadi"), 200
        if kind == "CONTRACT":
            if obj.remaining_balance <= 0 or obj.status in {ContractStatus.CLOSED, ContractStatus.CANCELLED}:
                return _paynet_err(rpc_id, 201, "Shartnoma qarzi allaqachon yopilgan"), 200
            if amount_uzs > obj.remaining_balance:
                return _paynet_err(rpc_id, 411, "To‘lov summasi qarz qoldig‘idan katta"), 200

        tx = PspTransaction.objects.create(
            psp_provider="Paynet",
            external_trans_id=tx_id,
            merchant_trans_id=ref,
            action_stage="PERFORMED",
            amount_tiyin=amount_tiyin,
            state_code=2,
            signature_verified=True,
            idempotency_key=f"paynet-uws-{tx_id}",
            order=obj if kind == "ORDER" else None,
            contract=obj if kind == "CONTRACT" else None,
            raw_payload_sanitized={"method": "PerformTransaction", "ref": ref, "amount_tiyin": amount_tiyin, "client_ip": client_ip},
            is_demo=settings.ZARVON_SANDBOX_MODE,
        )
        settled = settle_psp_payment(
            psp_provider="Paynet",
            target_kind=kind,
            target_obj=obj,
            amount_uzs=amount_uzs,
            idem_key=f"paynet-perf-{tx_id}",
            external_trans_id=f"PAYNET-{tx_id}",
        )
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "status": 0,
                "timeStamp": now_iso,
                "providerTrnId": str(tx.id),
                "payment_id": settled.get("payment_id"),
                "remaining_balance": settled.get("remaining_balance"),
                "fields": {"settled_uzs": amount_uzs, "target": ref},
            },
        }, 200

    if method == "CheckTransaction":
        tx_id = str(params.get("transactionId") or params.get("id") or "").strip()
        tx = PspTransaction.objects.filter(psp_provider="Paynet", external_trans_id=tx_id).first()
        if not tx:
            return _paynet_err(rpc_id, 202, "Tranzaksiya topilmadi"), 200
        tx_state = 2 if tx.action_stage == "CANCELLED" else 1
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "status": 0,
                "timeStamp": now_iso,
                "providerTrnId": str(tx.id),
                "transactionState": tx_state,
                "amount": tx.amount_tiyin,
            },
        }, 200

    if method == "CancelTransaction":
        tx_id = str(params.get("transactionId") or params.get("id") or "").strip()
        tx = PspTransaction.objects.select_for_update().filter(psp_provider="Paynet", external_trans_id=tx_id).first()
        if not tx:
            return _paynet_err(rpc_id, 202, "Tranzaksiya topilmadi"), 200
        if tx.action_stage != "CANCELLED":
            tx.action_stage = "CANCELLED"
            tx.state_code = -2
            raw = dict(tx.raw_payload_sanitized or {})
            raw["cancel_time_ms"] = int(timezone.now().timestamp() * 1000)
            tx.raw_payload_sanitized = raw
            tx.save(update_fields=["action_stage", "state_code", "raw_payload_sanitized", "updated_at"])
            PaymentRecord.objects.filter(payment_intent_id=f"PAYNET-{tx_id}").update(status="CANCELLED")
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "status": 0,
                "timeStamp": now_iso,
                "providerTrnId": str(tx.id),
                "transactionState": 2,
            },
        }, 200

    if method == "GetStatement":
        txs = PspTransaction.objects.filter(psp_provider="Paynet").order_by("-created_at")[:100]
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "status": 0,
                "statements": [
                    {
                        "transactionId": t.external_trans_id,
                        "providerTrnId": str(t.id),
                        "account": t.merchant_trans_id,
                        "amount": t.amount_tiyin,
                        "transactionState": 2 if t.action_stage == "CANCELLED" else 1,
                        "created_at": t.created_at.isoformat(),
                    }
                    for t in txs
                ],
            },
        }, 200

    return _paynet_err(rpc_id, -32601, f"Method not found: {method}"), 200
