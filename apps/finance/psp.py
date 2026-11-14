"""Click Merchant API, Payme JSON-RPC 2.0 & Uzum/Paynet Payment Gateway Protocol Adapters."""
import base64
import hashlib
import hmac
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


def verify_payme_auth(auth_header: str) -> bool:
    key = settings.PAYME_CASHBOX_KEY
    if not key or not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
        login, pw = decoded.split(":", 1)
    except Exception:
        return False
    return hmac.compare_digest(login, "Paycom") and hmac.compare_digest(pw, key)


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
        if not PaymentRecord.objects.filter(payment_intent_id=external_trans_id).exists():
            PaymentRecord.objects.create(
                payment_intent_id=external_trans_id,
                provider=psp_provider,
                user=order.customer,
                order=order,
                amount=amount_uzs,
                status="SUCCEEDED",
                reconciliation_ref=f"REC-{order.order_number}",
                is_demo=settings.ZARVON_SANDBOX_MODE,
            )
        if order.status in {OrderStatus.AWAITING_FINANCE, OrderStatus.PENDING}:
            order.status = OrderStatus.CONFIRMED
            order.save(update_fields=["status"])
            order.seller_orders.update(status=OrderStatus.CONFIRMED)
        return {"target": order.order_number, "settled_uzs": amount_uzs}

    if target_kind == "CONTRACT":
        contract = InstallmentContract.objects.select_for_update().get(id=target_obj.id)
        if RepaymentEvent.objects.filter(idempotency_key=idem_key).exists():
            return {"target": contract.contract_number, "idempotent_replay": True, "remaining_balance": contract.remaining_balance}
        applied = min(int(amount_uzs), contract.remaining_balance)
        if applied <= 0:
            return {"target": contract.contract_number, "remaining_balance": contract.remaining_balance}
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
        contract.save()
        RepaymentEvent.objects.create(
            contract=contract,
            amount=applied,
            payment_method=psp_provider,
            is_early_repayment=False,
            early_fee=0,
            idempotency_key=idem_key,
        )
        PaymentRecord.objects.create(
            payment_intent_id=external_trans_id,
            provider=psp_provider,
            user=contract.customer,
            contract=contract,
            amount=applied,
            status="SUCCEEDED",
            reconciliation_ref=f"REC-{contract.contract_number}",
            is_demo=settings.ZARVON_SANDBOX_MODE,
        )
        NotificationEvent.objects.create(
            user=contract.customer,
            channel="TELEGRAM",
            category="TRANSACTIONAL",
            status="delivered",
            title=f"{psp_provider} orqali to‘lov qabul qilindi ({applied:,} so‘m)",
            body_masked=f"Shartnoma #{contract.contract_number} bo‘yicha qoldiq: {contract.remaining_balance:,} so‘m.",
        )
        return {"target": contract.contract_number, "settled_uzs": applied, "remaining_balance": contract.remaining_balance}
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
        tx = PspTransaction.objects.filter(psp_provider="Click", merchant_prepare_id=prep_id, merchant_trans_id=merchant_trans_id).first()
        if not tx:
            return {"error": -6, "error_note": "Transaction does not exist"}
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
        settle_psp_payment(
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
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"allow": True}}

    if method == "CreateTransaction":
        payme_id = str(params.get("id") or "")
        ref = str((params.get("account") or {}).get("order_id") or (params.get("account") or {}).get("contract_id") or "")
        amount_tiyin = int(params.get("amount") or 0)
        kind, obj, expected_uzs = resolve_payment_target(ref)
        if not obj:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31050, "message": "Order/Contract not found"}}
        if kind == "ORDER" and amount_tiyin != expected_uzs * 100 or amount_tiyin <= 0:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31001, "message": "Invalid amount"}}

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
        if tx.state_code == 2:
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"transaction": str(tx.id), "perform_time": int(tx.updated_at.timestamp() * 1000), "state": 2}}
        tx.action_stage = "PERFORMED"
        tx.state_code = 2
        tx.save(update_fields=["action_stage", "state_code", "updated_at"])
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
                "perform_time": int(timezone.now().timestamp() * 1000),
                "state": 2,
            },
        }

    if method == "CancelTransaction":
        payme_id = str(params.get("id") or "")
        tx = PspTransaction.objects.select_for_update().filter(psp_provider="Payme", external_trans_id=payme_id).first()
        if not tx:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31003, "message": "Transaction not found"}}
        tx.action_stage = "CANCELLED"
        tx.state_code = -2 if tx.state_code == 2 else -1
        tx.save(update_fields=["action_stage", "state_code", "updated_at"])
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"transaction": str(tx.id), "cancel_time": int(timezone.now().timestamp() * 1000), "state": tx.state_code}}

    if method == "CheckTransaction":
        payme_id = str(params.get("id") or "")
        tx = PspTransaction.objects.filter(psp_provider="Payme", external_trans_id=payme_id).first()
        if not tx:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -31003, "message": "Transaction not found"}}
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"create_time": int(tx.created_at.timestamp() * 1000), "perform_time": int(tx.updated_at.timestamp() * 1000) if tx.state_code == 2 else 0, "cancel_time": 0, "transaction": str(tx.id), "state": tx.state_code}}

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
