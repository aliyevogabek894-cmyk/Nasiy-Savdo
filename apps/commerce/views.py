"""Cart, Multi-Seller Checkout, Atomic Reservations, Sub-Order Lifecycle, Delivery OTP & Returns."""
import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import ADMIN_ROLES, HasRolePermission
from config.utils import hash_token
from apps.catalog.models import Product, ProductStatus, PromoCode
from apps.commerce.models import (
    Cart,
    CartItem,
    DeliveryPoint,
    Order,
    OrderItem,
    OrderStatus,
    RefundRecord,
    ReturnRequest,
    SellerOrder,
    Shipment,
)
from apps.finance.models import (
    BankPartner,
    ContractStatus,
    CreditApplication,
    CustomerConsent,
    CustomerLimit,
    InstallmentContract,
    InstallmentPlan,
    LimitEvent,
    PaymentRecord,
    PspTransaction,
)
from apps.finance.providers import ComplianceViolationError, OwnInstallmentProvider, PartnerFinanceProvider
from apps.finance.psp import build_psp_checkout_payload
from apps.governance.models import AuditLog, BhmValue, ComplianceRuleVersion, NotificationEvent
from apps.inventory.models import Reservation, StockLevel, StockMovement


class DeliveryPointListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        pts = DeliveryPoint.objects.filter(is_active=True)
        return Response(
            {
                "results": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "region": p.region,
                        "address": p.address,
                        "working_hours": p.working_hours,
                    }
                    for p in pts
                ]
            }
        )


class CartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _serialize_cart(self, cart: Cart) -> dict:
        bhm_limit = BhmValue.get_current_amount() * ComplianceRuleVersion.get_active().max_bhm_multiplier
        items = list(cart.items.select_related("product__store", "product__category", "product__stock").prefetch_related("product__images"))
        subtotal = 0
        all_installment_ok = len(items) > 0
        prohibited_reasons = []
        serialized_items = []
        seller_groups = {}

        for ci in items:
            p = ci.product
            line_total = p.cash_price * ci.quantity
            subtotal += line_total
            cat_ok = p.category.installment_allowed and p.installment_eligible
            if not cat_ok:
                all_installment_ok = False
                prohibited_reasons.append(f"'{p.title}' toifasida nasiya taqiqlangan ({p.category.name}).")
            serialized_items.append(
                {
                    "item_id": str(ci.id),
                    "product_id": str(p.id),
                    "slug": p.slug,
                    "title": p.title,
                    "store_id": str(p.store_id),
                    "store_name": p.store.public_name,
                    "cash_price": p.cash_price,
                    "quantity": ci.quantity,
                    "line_total": line_total,
                    "stock_available": p.stock.available if hasattr(p, "stock") else 0,
                    "installment_eligible": cat_ok,
                    "primary_image": p.images.first().image_url if p.images.exists() else "",
                }
            )
            sg = seller_groups.setdefault(str(p.store_id), {"store_name": p.store.public_name, "items_count": 0, "subtotal": 0})
            sg["items_count"] += ci.quantity
            sg["subtotal"] += line_total

        if subtotal > bhm_limit:
            all_installment_ok = False
            prohibited_reasons.append(f"Jami summa 250 BHM ({bhm_limit:,} so‘m) chegarasidan oshdi.")

        return {
            "items": serialized_items,
            "seller_groups": list(seller_groups.values()),
            "subtotal": subtotal,
            "installment_eligible": all_installment_ok,
            "prohibited_reasons": prohibited_reasons,
            "bhm_limit": bhm_limit,
        }

    def get(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return Response(self._serialize_cart(cart))

    def post(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        product = Product.objects.filter(id=request.data.get("product_id"), status=ProductStatus.APPROVED).select_related("stock").first()
        if not product:
            return Response({"detail": "Mahsulot topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        avail = product.stock.available if hasattr(product, "stock") else 0
        delta = request.data.get("delta")
        if delta is not None:
            ci_cur = cart.items.filter(product=product).first()
            next_qty = (ci_cur.quantity if ci_cur else 0) + int(delta)
            if next_qty <= 0:
                if ci_cur:
                    ci_cur.delete()
                return Response(self._serialize_cart(cart))
            qty = next_qty
            set_exact = True
        else:
            raw_qty = request.data.get("quantity")
            set_exact = bool(request.data.get("set_exact"))
            if set_exact and raw_qty is not None and int(raw_qty) <= 0:
                cart.items.filter(product=product).delete()
                return Response(self._serialize_cart(cart))
            qty = max(1, int(raw_qty or 1))
        if avail < qty:
            return Response({"detail": f"Omborda faqat {avail} dona mavjud."}, status=status.HTTP_400_BAD_REQUEST)
        ci, created = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": qty})
        if not created:
            if set_exact:
                ci.quantity = qty
            else:
                ci.quantity = min(avail, ci.quantity + qty)
            ci.save()
        return Response(self._serialize_cart(cart))

    def delete(self, request):
        cart, _ = Cart.objects.get_or_create(user=request.user)
        product_id = request.query_params.get("product_id")
        if product_id:
            cart.items.filter(product_id=product_id).delete()
        else:
            cart.items.all().delete()
        return Response(self._serialize_cart(cart))


class CheckoutView(APIView):
    """3-step Idempotent Checkout creating atomic reservations, split SellerOrders & Nasiya/Bank Gateway."""

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        idem_key = (request.data.get("idempotency_key") or f"chk-{uuid.uuid4().hex[:14]}").strip()
        existing = Order.objects.filter(idempotency_key=idem_key).first()
        if existing:
            return Response({"ok": True, "order_id": str(existing.id), "order_number": existing.order_number, "idempotent_replay": True})

        cart, _ = Cart.objects.get_or_create(user=request.user)
        items_input = request.data.get("items")  # Optional direct item checkout [{product_id, quantity}]
        checkout_lines = []
        if items_input:
            for row in items_input:
                p = Product.objects.filter(id=row["product_id"], status=ProductStatus.APPROVED).select_related("store", "category", "stock").first()
                if not p:
                    return Response({"detail": "Savatdagi mahsulot mavjud emas yoki tasdiqlanmagan."}, status=status.HTTP_400_BAD_REQUEST)
                checkout_lines.append((p, max(1, int(row.get("quantity") or 1))))
        else:
            for ci in cart.items.select_related("product__store", "product__category", "product__stock"):
                if ci.product.status != ProductStatus.APPROVED:
                    return Response({"detail": f"'{ci.product.title}' moderatsiyadan o‘tmagan."}, status=status.HTTP_400_BAD_REQUEST)
                checkout_lines.append((ci.product, ci.quantity))

        if not checkout_lines:
            return Response({"detail": "Buyurtma uchun savat bo‘sh."}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate live prices & apply promo
        subtotal = sum(p.cash_price * qty for p, qty in checkout_lines)
        discount = 0
        promo_code = (request.data.get("promo_code") or "").strip().upper()
        if promo_code:
            promo = PromoCode.objects.filter(code=promo_code, is_active=True, expires_at__gte=timezone.now()).first()
            if promo and subtotal >= promo.min_order_amount:
                raw_disc = promo.discount_fixed if promo.discount_fixed > 0 else round(subtotal * promo.discount_pct / 100.0)
                discount = min(raw_disc, max(0, promo.max_budget_uzs - promo.used_budget_uzs))
                promo.used_budget_uzs += discount
                promo.save(update_fields=["used_budget_uzs"])
        total_amount = max(1000, subtotal - discount)

        payment_channel = request.data.get("payment_channel") or "DIRECT_PAY"
        payment_method_label = request.data.get("payment_method_label") or "Payme (Sandbox)"
        delivery_type = request.data.get("delivery_type") or "COURIER"
        delivery_address = (request.data.get("delivery_address") or "Toshkent shahri").strip()
        delivery_point = None
        if delivery_type == "PICKUP" and request.data.get("delivery_point_id"):
            delivery_point = DeliveryPoint.objects.filter(id=request.data["delivery_point_id"]).first()

        order_num = f"ZRV-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:5].upper()}"

        # Reserve inventory atomically BEFORE finalizing order (oversell prevention)
        for p, qty in checkout_lines:
            try:
                Reservation.reserve_for_order(p.id, qty, order_num, actor=request.user)
            except ValueError as err:
                transaction.set_rollback(True)
                return Response({"detail": f"{p.title}: {err}"}, status=status.HTTP_409_CONFLICT)

        initial_order_status = OrderStatus.CONFIRMED if payment_channel == "DIRECT_PAY" else OrderStatus.AWAITING_FINANCE
        master = Order.objects.create(
            order_number=order_num,
            customer=request.user,
            payment_channel=payment_channel,
            payment_method_label=payment_method_label,
            delivery_type=delivery_type,
            delivery_address=delivery_address,
            delivery_point=delivery_point,
            promo_code_used=promo_code,
            subtotal_amount=subtotal,
            discount_amount=discount,
            total_amount=total_amount,
            status=initial_order_status,
            idempotency_key=idem_key,
        )

        # Group by Store -> create Seller Sub-Orders & immutable OrderItem price snapshots
        by_store = {}
        for p, qty in checkout_lines:
            by_store.setdefault(p.store_id, {"store": p.store, "lines": []})["lines"].append((p, qty))

        sub_orders_out = []
        for idx, (_, group) in enumerate(by_store.items(), start=1):
            st = group["store"]
            sub_tot = sum(p.cash_price * qty for p, qty in group["lines"])
            comm = round(sub_tot * (st.commission_pct / 100.0))
            holdback = round(sub_tot * (st.holdback_pct / 100.0))
            net_pay = max(0, sub_tot - comm - holdback)
            so = SellerOrder.objects.create(
                master_order=master,
                store=st,
                sub_order_number=f"{order_num}-S{idx}",
                subtotal_amount=sub_tot,
                commission_amount=comm,
                holdback_amount=holdback,
                net_seller_payout=net_pay,
                status=initial_order_status,
            )
            delivery_otp = so.issue_delivery_otp()
            for p, qty in group["lines"]:
                OrderItem.objects.create(
                    seller_order=so,
                    product=p,
                    product_title_snapshot=p.title,
                    sku_snapshot=p.sku,
                    unit_price_snapshot=p.cash_price,
                    quantity=qty,
                    line_total=p.cash_price * qty,
                )
                p.sales_count += qty
                p.save(update_fields=["sales_count"])
            Shipment.objects.create(
                seller_order=so,
                tracking_number=f"TRK-{uuid.uuid4().hex[:8].upper()}",
                estimated_delivery=timezone.now().date() + timezone.timedelta(days=2),
            )
            sub_orders_out.append({"sub_order_number": so.sub_order_number, "store": st.public_name, "delivery_otp_demo": delivery_otp})

        finance_result = {}

        if payment_channel == "ZARVON_NASIYA":
            # Enforce explicit consent (Section 8.1 / 23.1)
            has_id_consent = CustomerConsent.objects.filter(user=request.user, purpose="IDENTITY", is_granted=True, revoked_at__isnull=True).exists()
            has_cb_consent = CustomerConsent.objects.filter(user=request.user, purpose="CREDIT_BUREAU", is_granted=True, revoked_at__isnull=True).exists()
            if not (has_id_consent and has_cb_consent):
                transaction.set_rollback(True)
                return Response(
                    {"detail": "Nasiya shartnomasi uchun shaxsni tekshirish va kredit hisoboti roziliklari alohida berilishi shart (28.4)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            plan = InstallmentPlan.objects.filter(id=request.data.get("plan_id"), is_active=True).first() or InstallmentPlan.objects.filter(is_active=True, months=12).first()
            down_payment = max(0, min(total_amount - 100000, int(request.data.get("down_payment") or 0)))
            principal = total_amount - down_payment
            cat_allowed = all(p.category.installment_allowed and p.installment_eligible for p, _ in checkout_lines)

            try:
                provider = OwnInstallmentProvider()
                quote = provider.calculate_quote(principal=principal, months=plan.months, plan=plan, category_allowed=cat_allowed)
            except ComplianceViolationError as exc:
                transaction.set_rollback(True)
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            lim, _ = CustomerLimit.objects.select_for_update().get_or_create(user=request.user)
            if lim.available_limit_uzs < principal:
                transaction.set_rollback(True)
                return Response(
                    {"detail": f"Bo‘sh nasiya limitingiz yetarli emas (mavjud: {lim.available_limit_uzs:,} so‘m, talab: {principal:,} so‘m)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # High-resell risk signal check for brand-new low-tier customer (Section 31.1)
            if any(p.resell_risk_level == "HIGH" for p, _ in checkout_lines) and lim.tier == "Start" and principal > 8_000_000:
                from apps.risk_collections.models import FraudCase, FraudSignal
                sig = FraudSignal.objects.create(
                    user=request.user,
                    signal_type="HIGH_RESELL_RISK",
                    severity="MEDIUM",
                    summary=f"Yangi Start mijoz yuqori qayta sotish xavfli tovarga ({principal:,} so‘m) nasiya so‘radi.",
                    metadata={"order_number": order_num, "principal": principal},
                )
                FraudCase.objects.create(signal=sig, status="OPEN")

            contract_num = f"NSY-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:5].upper()}"
            contract = InstallmentContract.objects.create(
                contract_number=contract_num,
                order=master,
                customer=request.user,
                plan=plan,
                provider_type="OWN_NASIYA",
                provider_name="ZARVON Nasiya Operator (Sandbox DEMO)",
                principal_amount=principal,
                down_payment=down_payment,
                markup_amount=quote["markup_amount"],
                commission_amount=quote["commission_amount"],
                total_payable=quote["total_payable"],
                remaining_balance=quote["total_payable"],
                months=plan.months,
                status=ContractStatus.SIGNED,
                signed_method=request.data.get("signed_method") or "OTP",
                signed_at=timezone.now(),
                compliance_rule_code=quote["compliance_version"],
                bhm_snapshot_uzs=quote["bhm_amount"],
                summary_terms={
                    "monthly_payment": quote["monthly_payment"],
                    "annualized_extra_pct": quote["annualized_extra_pct"],
                    "early_repayment_fee": "0 so‘m (istalgan vaqtda jarimasiz)",
                    "complaint_rights": "Shikoyat va apellyatsiya: kabinetdagi Murojaatlar bo‘limi orqali",
                },
            )
            provider.build_schedule(contract=contract)
            lim.used_limit_uzs += principal
            lim.save(update_fields=["used_limit_uzs", "updated_at"])
            LimitEvent.objects.create(
                customer_limit=lim,
                event_type="UTILIZE",
                amount_delta=-principal,
                reason=f"Nasiya shartnomasi #{contract_num}",
                actor=request.user,
            )
            master.status = OrderStatus.CONFIRMED
            master.save(update_fields=["status"])
            master.seller_orders.update(status=OrderStatus.CONFIRMED)
            finance_result = {
                "contract_id": str(contract.id),
                "contract_number": contract.contract_number,
                "monthly_payment": quote["monthly_payment"],
                "total_payable": contract.total_payable,
            }

        elif payment_channel == "BANK_GATEWAY":
            has_bank_consent = CustomerConsent.objects.filter(user=request.user, purpose="BANK_TRANSFER", is_granted=True, revoked_at__isnull=True).exists()
            has_cb_consent = CustomerConsent.objects.filter(user=request.user, purpose="CREDIT_BUREAU", is_granted=True, revoked_at__isnull=True).exists()
            if not (has_bank_consent and has_cb_consent):
                transaction.set_rollback(True)
                return Response({"detail": "Bankka ariza yuborish uchun ma’lumot uzatish va kredit hisoboti roziligi majburiy."}, status=status.HTTP_400_BAD_REQUEST)

            months = min(12, max(3, int(request.data.get("months") or 12)))
            corr_id = f"ZRV-GW-{uuid.uuid4().hex[:8].upper()}"
            credit_app = CreditApplication.objects.create(
                application_number=f"APP-{uuid.uuid4().hex[:8].upper()}",
                customer=request.user,
                order=master,
                requested_amount=total_amount,
                requested_months=months,
                status="Bank Submitted",
                correlation_id=corr_id,
            )
            banks = list(BankPartner.objects.filter(is_active=True))
            bank_results = PartnerFinanceProvider().dispatch_to_banks(credit_application=credit_app, banks=banks, base_correlation_id=corr_id)
            finance_result = {
                "credit_application_id": str(credit_app.id),
                "application_number": credit_app.application_number,
                "bank_results": bank_results,
            }

        else:
            # Direct Pay via local PSP adapter (Payme / Click / Uzum Bank / Paynet / Uzcard-Humo)
            psp_name = str(request.data.get("psp_provider") or "Payme").strip()
            ext_id = f"PAY-{uuid.uuid4().hex[:10].upper()}"
            PaymentRecord.objects.create(
                payment_intent_id=ext_id,
                provider=psp_name,
                user=request.user,
                order=master,
                amount=total_amount,
                status="SUCCEEDED",
                reconciliation_ref=f"REC-{order_num}",
                is_demo=settings.ZARVON_SANDBOX_MODE,
            )
            PspTransaction.objects.create(
                psp_provider=psp_name,
                external_trans_id=ext_id,
                merchant_trans_id=order_num,
                action_stage="PERFORMED",
                amount_tiyin=int(total_amount) * 100,
                state_code=2,
                signature_verified=True,
                idempotency_key=f"direct-{ext_id}",
                order=master,
                raw_payload_sanitized={"channel": "CHECKOUT_DIRECT_PAY", "psp": psp_name, "sandbox": settings.ZARVON_SANDBOX_MODE},
                is_demo=settings.ZARVON_SANDBOX_MODE,
            )
            finance_result = {**(finance_result or {}), "psp_checkout": build_psp_checkout_payload(psp_provider=psp_name, reference=order_num, amount_uzs=total_amount)}

        if not items_input:
            cart.items.all().delete()

        NotificationEvent.objects.create(
            user=request.user,
            channel="SMS",
            category="TRANSACTIONAL",
            status="delivered",
            title=f"Buyurtma #{order_num} qabul qilindi",
            body_masked=f"Buyurtma summasi: {total_amount:,} so‘m. Yetkazib berishda OTP koddan foydalaning.",
        )
        AuditLog.record(actor=request.user, action="ORDER_CREATED", object_type="Order", object_id=master.id, reason=f"Kanal: {payment_channel}", after={"order_number": order_num, "total_amount": total_amount})
        return Response({"ok": True, "order_id": str(master.id), "order_number": order_num, "sub_orders": sub_orders_out, "finance": finance_result, "total_amount": total_amount}, status=status.HTTP_201_CREATED)


class OrdersListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role in {"SELLER_OWNER", "SELLER_STAFF"}:
            sub_qs = SellerOrder.objects.filter(store_id__in=user.get_accessible_store_ids()).select_related("master_order__customer", "store", "shipment").prefetch_related("items", "return_requests")
            return Response(
                {
                    "mode": "seller",
                    "seller_orders": [
                        {
                            "id": str(so.id),
                            "sub_order_number": so.sub_order_number,
                            "master_order_number": so.master_order.order_number,
                            "customer_name": so.master_order.customer.full_name,
                            "delivery_type": so.master_order.delivery_type,
                            "delivery_address": so.master_order.delivery_address,
                            "subtotal_amount": so.subtotal_amount,
                            "commission_amount": so.commission_amount,
                            "holdback_amount": so.holdback_amount,
                            "net_seller_payout": so.net_seller_payout,
                            "payout_status": so.payout_status,
                            "status": so.status,
                            "tracking_number": so.shipment.tracking_number if hasattr(so, "shipment") else "",
                            "created_at": so.created_at,
                            "items": [
                                {"title": it.product_title_snapshot, "sku": it.sku_snapshot, "qty": it.quantity, "unit_price": it.unit_price_snapshot, "line_total": it.line_total}
                                for it in so.items.all()
                            ],
                            "returns": [{"id": str(r.id), "status": r.status, "reason": r.reason, "scope": r.return_scope} for r in so.return_requests.all()],
                        }
                        for so in sub_qs[:50]
                    ],
                }
            )

        if user.role in ADMIN_ROLES:
            qs = Order.objects.select_related("customer").prefetch_related("seller_orders__items", "seller_orders__store", "seller_orders__shipment", "seller_orders__return_requests").all()[:50]
        else:
            qs = Order.objects.filter(customer=user).prefetch_related("seller_orders__items", "seller_orders__store", "seller_orders__shipment", "seller_orders__return_requests")[:30]

        return Response(
            {
                "mode": "master",
                "orders": [
                    {
                        "id": str(o.id),
                        "order_number": o.order_number,
                        "customer_name": o.customer.full_name,
                        "payment_channel": o.payment_channel,
                        "payment_method_label": o.payment_method_label,
                        "delivery_type": o.delivery_type,
                        "delivery_address": o.delivery_address,
                        "total_amount": o.total_amount,
                        "discount_amount": o.discount_amount,
                        "status": o.status,
                        "created_at": o.created_at,
                        "seller_orders": [
                            {
                                "id": str(so.id),
                                "sub_order_number": so.sub_order_number,
                                "store_name": so.store.public_name,
                                "status": so.status,
                                "subtotal_amount": so.subtotal_amount,
                                "tracking_number": so.shipment.tracking_number if hasattr(so, "shipment") else "",
                                # Delivery OTP visible ONLY to customer or admin in sandbox
                                "delivery_otp_demo": so.delivery_otp_demo if (o.customer_id == user.id or user.role in ADMIN_ROLES) else None,
                                "items": [
                                    {"product_id": str(it.product_id), "title": it.product_title_snapshot, "qty": it.quantity, "unit_price": it.unit_price_snapshot, "line_total": it.line_total}
                                    for it in so.items.all()
                                ],
                                "returns": [{"id": str(r.id), "status": r.status, "reason": r.reason, "refund_amount": r.refund_amount} for r in so.return_requests.all()],
                            }
                            for so in o.seller_orders.all()
                        ],
                    }
                    for o in qs
                ],
            }
        )


class SellerOrderStatusUpdateView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN", "DELIVERY_MANAGER", "SELLER_OWNER", "SELLER_STAFF"}

    @transaction.atomic
    def post(self, request, pk):
        so = SellerOrder.objects.select_for_update().select_related("master_order", "store").filter(id=pk).first()
        if not so:
            return Response({"detail": "Sub-buyurtma topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.role in {"SELLER_OWNER", "SELLER_STAFF"} and so.store_id not in request.user.get_accessible_store_ids():
            return Response({"detail": "Boshqa sotuvchi buyurtmasini boshqarish taqiqlangan."}, status=status.HTTP_403_FORBIDDEN)

        new_status = request.data.get("status")
        if new_status not in OrderStatus.values:
            return Response({"detail": "Noto‘g‘ri holat."}, status=status.HTTP_400_BAD_REQUEST)

        if new_status == OrderStatus.DELIVERED:
            otp_code = (request.data.get("delivery_otp") or "").strip()
            if not otp_code or hash_token(otp_code) != so.delivery_otp_hash:
                return Response({"detail": "Topshirish OTP-kodi noto‘g‘ri yoki kiritilmagan (28.4 / 31.1)."}, status=status.HTTP_400_BAD_REQUEST)
            so.delivered_at = timezone.now()
            so.payout_status = "SCHEDULED"
            # Consume stock reservations
            for res in Reservation.objects.filter(order_ref=so.master_order.order_number, status="ACTIVE"):
                st = res.stock
                if st.product.store_id == so.store_id:
                    st.reserved = max(0, st.reserved - res.quantity)
                    st.quantity = max(0, st.quantity - res.quantity)
                    st.save()
                    res.status = "CONSUMED"
                    res.save()
                    StockMovement.objects.create(stock=st, movement_type="OUTBOUND", delta=-res.quantity, note=f"Topshirildi {so.sub_order_number}", created_by=request.user)
            # Activate installment contract after delivery (28.4)
            if hasattr(so.master_order, "installment_contract"):
                c = so.master_order.installment_contract
                if c.status == ContractStatus.SIGNED:
                    c.status = ContractStatus.ACTIVE
                    c.save(update_fields=["status"])

        elif new_status == OrderStatus.CANCELLED:
            so.cancel_reason = (request.data.get("reason") or "Bekor qilindi").strip()
            for res in Reservation.objects.filter(order_ref=so.master_order.order_number, status="ACTIVE"):
                st = res.stock
                if st.product.store_id == so.store_id:
                    st.reserved = max(0, st.reserved - res.quantity)
                    st.save()
                    res.status = "RELEASED"
                    res.save()
                    StockMovement.objects.create(stock=st, movement_type="RELEASE", delta=res.quantity, note=f"Bekor qilindi {so.sub_order_number}", created_by=request.user)

        elif new_status == OrderStatus.SHIPPED and hasattr(so, "shipment"):
            so.shipment.shipped_at = timezone.now()
            if request.data.get("courier_name"):
                so.shipment.courier_name = request.data["courier_name"]
            so.shipment.save()

        so.status = new_status
        so.save()

        # Sync master order status cleanly
        statuses = list(so.master_order.seller_orders.values_list("status", flat=True))
        if all(s == OrderStatus.DELIVERED for s in statuses):
            so.master_order.status = OrderStatus.DELIVERED
        elif all(s == OrderStatus.CANCELLED for s in statuses):
            so.master_order.status = OrderStatus.CANCELLED
        elif OrderStatus.SHIPPED in statuses:
            so.master_order.status = OrderStatus.SHIPPED
        elif OrderStatus.PROCESSING in statuses:
            so.master_order.status = OrderStatus.PROCESSING
        so.master_order.save(update_fields=["status"])

        AuditLog.record(actor=request.user, action=f"ORDER_{new_status.upper()}", object_type="SellerOrder", object_id=so.id, reason=so.cancel_reason or f"Holat: {new_status}")
        return Response({"ok": True, "status": so.status})


class ReturnRequestCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        so = SellerOrder.objects.filter(id=pk, master_order__customer=request.user).first()
        if not so:
            return Response({"detail": "Buyurtma topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "Qaytarish sababini yozing."}, status=status.HTTP_400_BAD_REQUEST)
        scope = request.data.get("return_scope") or "FULL"
        refund_amt = so.subtotal_amount if scope == "FULL" else min(so.subtotal_amount, int(request.data.get("refund_amount") or so.subtotal_amount // 2))
        rr = ReturnRequest.objects.create(
            seller_order=so,
            customer=request.user,
            return_scope=scope,
            refund_amount=refund_amt,
            reason=reason,
            photo_evidence_note=request.data.get("photo_evidence_note", "Foto dalil biriktirilgan"),
        )
        so.status = OrderStatus.RETURN_REQUESTED
        so.save(update_fields=["status"])
        AuditLog.record(actor=request.user, action="RETURN_REQUESTED", object_type="ReturnRequest", object_id=rr.id, reason=reason)
        return Response({"ok": True, "return_id": str(rr.id)}, status=status.HTTP_201_CREATED)


class ReturnDecisionView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN", "FINANCE_OPERATIONS", "SELLER_OWNER", "SELLER_STAFF"}

    @transaction.atomic
    def post(self, request, pk):
        rr = ReturnRequest.objects.select_for_update().select_related("seller_order__master_order", "seller_order__store").filter(id=pk).first()
        if not rr:
            return Response({"detail": "Qaytarish so‘rovi topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.role in {"SELLER_OWNER", "SELLER_STAFF"} and rr.seller_order.store_id not in request.user.get_accessible_store_ids():
            return Response({"detail": "Ruxsat yo‘q."}, status=status.HTTP_403_FORBIDDEN)

        decision = request.data.get("decision")  # APPROVED / REJECTED
        note = (request.data.get("decision_note") or "").strip()
        if decision not in {"APPROVED", "REJECTED"} or not note:
            return Response({"detail": "Qaror va izoh majburiy."}, status=status.HTTP_400_BAD_REQUEST)

        rr.status = "REFUNDED" if decision == "APPROVED" else "REJECTED"
        rr.decision_note = note
        rr.handled_by = request.user
        rr.save()

        if decision == "APPROVED":
            so = rr.seller_order
            so.status = OrderStatus.RETURNED_REFUNDED
            so.payout_status = "ADJUSTED"
            so.net_seller_payout = max(0, so.net_seller_payout - rr.refund_amount)
            so.save()
            RefundRecord.objects.create(
                return_request=rr,
                amount=rr.refund_amount,
                channel=so.master_order.payment_channel,
                reconciliation_ref=f"REF-{so.sub_order_number}",
            )
            # Adjust installment contract if order used ZARVON Nasiya (Section 28.6)
            if hasattr(so.master_order, "installment_contract"):
                contract = so.master_order.installment_contract
                if rr.return_scope == "FULL":
                    contract.status = ContractStatus.CANCELLED
                    contract.remaining_balance = 0
                    contract.schedule_items.filter(status__in=["UPCOMING", "OVERDUE"]).update(status="WAIVED")
                    contract.save()
                else:
                    contract.remaining_balance = max(0, contract.remaining_balance - rr.refund_amount)
                    contract.save()
                lim = CustomerLimit.objects.filter(user=contract.customer).first()
                if lim:
                    restored = min(lim.used_limit_uzs, rr.refund_amount)
                    lim.used_limit_uzs -= restored
                    lim.save()
                    LimitEvent.objects.create(customer_limit=lim, event_type="RESTORE", amount_delta=restored, reason=f"Qaytarish #{so.sub_order_number}", actor=request.user)

        AuditLog.record(actor=request.user, action=f"RETURN_{decision}", object_type="ReturnRequest", object_id=rr.id, reason=note)
        return Response({"ok": True, "status": rr.status})
