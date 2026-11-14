"""Comprehensive automated acceptance, compliance, RBAC, security & concurrency tests (Section 23)."""
import io
import uuid
import openpyxl
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import MakerCheckerRequest, User, UserRole
from apps.catalog.models import Brand, Category, Product, ProductStatus
from apps.commerce.models import OrderItem
from apps.finance.models import BankPartner, CustomerConsent, CustomerLimit, InstallmentPlan, WebhookEvent
from apps.governance.models import BhmValue, ComplianceRuleVersion
from apps.inventory.models import StockLevel, Warehouse
from apps.sellers.models import SellerInvitation, Store


class ZarvonMasterSpecificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.bhm = BhmValue.objects.create(amount_uzs=440_000, effective_from=timezone.now().date(), is_active=True)
        self.rule = ComplianceRuleVersion.get_active()

        self.super_admin = User.objects.create_user("+998909000001", "Pass1234!", full_name="Super Admin", role=UserRole.SUPER_ADMIN, mfa_enabled=True)
        self.mkt_admin = User.objects.create_user("+998909000002", "Pass1234!", full_name="Market Admin", role=UserRole.MARKETPLACE_ADMIN, mfa_enabled=True)
        self.auditor = User.objects.create_user("+998909000003", "Pass1234!", full_name="Auditor", role=UserRole.AUDITOR)
        self.content_mgr = User.objects.create_user("+998909000004", "Pass1234!", full_name="Content Mgr", role=UserRole.CONTENT_MANAGER)

        self.seller_a = User.objects.create_user("+998902000001", "Pass1234!", full_name="Seller A", role=UserRole.SELLER_OWNER)
        self.seller_b = User.objects.create_user("+998902000002", "Pass1234!", full_name="Seller B", role=UserRole.SELLER_OWNER)
        self.customer = User.objects.create_user("+998901000001", "Pass1234!", full_name="Mijoz 1", role=UserRole.CUSTOMER)
        CustomerLimit.objects.create(user=self.customer, tier="Plus", total_limit_uzs=25_000_000, used_limit_uzs=0)

        self.store_a = Store.objects.create(owner=self.seller_a, legal_name="Store A MChJ", public_name="Store A", slug="store-a", official_phone="+998711111111", legal_address="Toshkent", return_address="Toshkent")
        self.store_b = Store.objects.create(owner=self.seller_b, legal_name="Store B MChJ", public_name="Store B", slug="store-b", official_phone="+998712222222", legal_address="Toshkent", return_address="Toshkent")
        self.wh_a = Warehouse.objects.create(store=self.store_a, name="WH A", address="Toshkent")

        self.cat_phone = Category.objects.create(name="Smartfonlar", slug="smartfonlar", installment_allowed=True)
        self.cat_realty = Category.objects.create(name="Ko‘chmas mulk", slug="kochmas-mulk", installment_allowed=False)
        self.brand_apple = Brand.objects.create(name="Apple", slug="apple")

        self.prod_a = Product.objects.create(
            store=self.store_a, category=self.cat_phone, brand=self.brand_apple,
            sku="APL-16-T", title="Apple iPhone 16 Titan", slug="apple-iphone-16-titan",
            description="Original telefon", cash_price=10_000_000, status=ProductStatus.APPROVED,
        )
        StockLevel.objects.create(product=self.prod_a, warehouse=self.wh_a, quantity=3)

        self.prod_pending = Product.objects.create(
            store=self.store_b, category=self.cat_phone, brand=self.brand_apple,
            sku="B-PEND-1", title="Tasdiqlanmagan Tovar", slug="tasdiqlanmagan-tovar",
            description="Hali moderatsiyada", cash_price=2_000_000, status=ProductStatus.PENDING_REVIEW,
        )
        self.plan12 = InstallmentPlan.objects.create(name="12 oy", months=12, annual_markup_pct=28.0, commission_pct=2.0)

    def test_compliance_guard_rejects_over_12_months_and_over_50pct_and_over_250_bhm_and_realty(self):
        # > 12 months rejected
        with self.assertRaises(ValidationError):
            InstallmentPlan.objects.create(name="Bad 18m", months=18, annual_markup_pct=20.0, commission_pct=1.0)
        # > 50% annual extra rejected
        with self.assertRaises(ValidationError):
            InstallmentPlan.objects.create(name="Usury 60%", months=12, annual_markup_pct=55.0, commission_pct=2.0)
        # > 250 BHM rejected by calculator API
        resp = self.client.post("/api/v1/finance/calculator/", {"price": 120_000_000, "months": 12}, format="json")
        self.assertEqual(resp.status_code, 400)
        # Prohibited category rejected
        resp2 = self.client.post("/api/v1/finance/calculator/", {"price": 5_000_000, "months": 12, "category_installment_allowed": False}, format="json")
        self.assertEqual(resp2.status_code, 400)

    def test_rbac_and_seller_tenant_isolation_and_auditor_readonly(self):
        # Seller B cannot edit Seller A's product
        self.client.force_authenticate(user=self.seller_b)
        res = self.client.patch(f"/api/v1/sellers/my-products/{self.prod_a.id}/", {"cash_price": 5_000_000}, format="json")
        self.assertEqual(res.status_code, 403)

        # Customer cannot open admin dashboard
        self.client.force_authenticate(user=self.customer)
        self.assertEqual(self.client.get("/api/v1/risk/dashboard/").status_code, 403)

        # Auditor can read dashboard, cannot mutate
        self.client.force_authenticate(user=self.auditor)
        self.assertEqual(self.client.get("/api/v1/risk/dashboard/").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/sellers/invitations/", {"company_name": "X", "target_phone": "+998901112233"}, format="json").status_code, 403)

        # Content manager cannot create promos (Section 33)
        self.client.force_authenticate(user=self.content_mgr)
        self.assertEqual(self.client.post("/api/v1/catalog/cms/", {"kind": "promo", "code": "HACK99", "title": "X"}, format="json").status_code, 403)

    def test_unapproved_product_hidden_from_public_catalog_and_smart_uzbek_search(self):
        resp = self.client.get("/api/v1/catalog/products/?q=айфон")
        self.assertEqual(resp.status_code, 200)
        titles = [x["title"] for x in resp.json()["results"]]
        self.assertIn("Apple iPhone 16 Titan", titles)
        self.assertNotIn("Tasdiqlanmagan Tovar", titles)

    def test_seller_invitation_hash_and_single_use(self):
        inv, raw = SellerInvitation.issue_invitation(company_name="Yangi", target_phone="+998907778899", target_email="", expires_hours=24, created_by=self.mkt_admin)
        self.assertNotEqual(inv.token_hash, raw)
        res1 = self.client.post("/api/v1/sellers/onboarding/verify-invite/", {"token": raw}, format="json")
        self.assertEqual(res1.status_code, 200)

        # Submit onboarding consumes token
        res_sub = self.client.post(
            "/api/v1/sellers/onboarding/submit/",
            {
                "token": raw, "legal_name": "Yangi MChJ", "public_name": "Yangi",
                "representative_name": "Ali", "official_phone": "+998907778899",
                "terms_accepted": True,
            },
            format="json",
        )
        self.assertEqual(res_sub.status_code, 201)
        # Second verify must fail (single-use)
        res2 = self.client.post("/api/v1/sellers/onboarding/verify-invite/", {"token": raw}, format="json")
        self.assertEqual(res2.status_code, 400)

    def test_consent_gate_oversell_prevention_price_snapshot_and_early_repayment(self):
        self.client.force_authenticate(user=self.customer)
        # Missing consents blocks Nasiya checkout
        res_no_consent = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": "chk-noconsent",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 1}],
                "payment_channel": "ZARVON_NASIYA",
                "plan_id": str(self.plan12.id),
            },
            format="json",
        )
        self.assertEqual(res_no_consent.status_code, 400)

        # Grant required consents
        CustomerConsent.objects.create(user=self.customer, purpose="IDENTITY", is_granted=True)
        CustomerConsent.objects.create(user=self.customer, purpose="CREDIT_BUREAU", is_granted=True)

        # Oversell (>3 available) blocked with 409 Conflict
        res_oversell = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": "chk-oversell",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 5}],
                "payment_channel": "ZARVON_NASIYA",
                "plan_id": str(self.plan12.id),
            },
            format="json",
        )
        self.assertEqual(res_oversell.status_code, 409)

        # Valid checkout succeeds
        res_ok = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": "chk-valid-1",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 1}],
                "payment_channel": "ZARVON_NASIYA",
                "plan_id": str(self.plan12.id),
            },
            format="json",
        )
        self.assertEqual(res_ok.status_code, 201)
        contract_id = res_ok.json()["finance"]["contract_id"]
        total_payable = res_ok.json()["finance"]["total_payable"]

        # Subsequent price change does NOT mutate OrderItem snapshot
        self.prod_a.cash_price = 15_000_000
        self.prod_a.save()
        item_snap = OrderItem.objects.filter(product=self.prod_a).first()
        self.assertEqual(item_snap.unit_price_snapshot, 10_000_000)

        # Unverified non-delivered purchase review is blocked
        rev_resp = self.client.post(f"/api/v1/catalog/products/{self.prod_a.id}/reviews/", {"rating": 5, "comment": "Test"}, format="json")
        self.assertEqual(rev_resp.status_code, 403)

        # Full early repayment incurs 0 fee and restores customer limit
        rep_resp = self.client.post(
            f"/api/v1/finance/contracts/{contract_id}/repay/",
            {"amount": total_payable, "is_early_repayment": True, "idempotency_key": "rep-early-1"},
            format="json",
        )
        self.assertEqual(rep_resp.status_code, 200)
        self.assertEqual(rep_resp.json()["early_fee"], 0)
        self.assertEqual(rep_resp.json()["remaining_balance"], 0)
        self.assertEqual(rep_resp.json()["contract_status"], "Prepaid")
        self.customer.installment_limit.refresh_from_db()
        self.assertEqual(self.customer.installment_limit.used_limit_uzs, 0)

    def test_xlsx_import_sanitization_and_ssrf_block(self):
        self.client.force_authenticate(user=self.seller_a)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["sku", "title", "category_slug", "brand", "cash_price", "stock"])
        ws.append(["GOOD-1", "Yangi Telefon", "smartfonlar", "Apple", 5000000, 4])
        ws.append(["BAD-1", "=HYPERLINK(\"evil\")", "smartfonlar", "Apple", -100, 1])
        buf = io.BytesIO()
        wb.save(buf)
        upload = SimpleUploadedFile("test_import.xlsx", buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp = self.client.post("/api/v1/imports/upload/", {"file": upload, "idempotency_key": f"imp-{uuid.uuid4().hex}"}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["summary"]["new"], 1)
        self.assertEqual(resp.json()["summary"]["error"], 1)

        # SSRF private metadata IP must be blocked
        ssrf = self.client.post("/api/v1/imports/integrations/", {"provider_name": "Evil", "endpoint_url": "http://169.254.169.254/latest/meta-data/"}, format="json")
        self.assertEqual(ssrf.status_code, 400)

    def test_multibank_partial_failure_webhook_and_maker_checker(self):
        BankPartner.objects.create(name="Bank OK", code="BOK", adapter_status="ONLINE", base_annual_rate_pct=26.0)
        BankPartner.objects.create(name="Bank Down", code="BDN", adapter_status="TIMEOUT", base_annual_rate_pct=25.0)
        CustomerConsent.objects.create(user=self.customer, purpose="BANK_TRANSFER", is_granted=True)
        CustomerConsent.objects.create(user=self.customer, purpose="CREDIT_BUREAU", is_granted=True)

        self.client.force_authenticate(user=self.customer)
        gw = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": "chk-gw-1",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 1}],
                "payment_channel": "BANK_GATEWAY",
                "months": 12,
            },
            format="json",
        )
        self.assertEqual(gw.status_code, 201)
        bank_results = gw.json()["finance"]["bank_results"]
        self.assertEqual(len(bank_results), 2)
        self.assertTrue(any(r["status"] == "Offer Available" for r in bank_results))
        self.assertTrue(any(r["status"] == "Bank response pending" for r in bank_results))

        # Webhook invalid signature -> 401; duplicate event_id -> idempotent replay
        bad_wh = self.client.post("/api/v1/finance/webhooks/bank/", {"event_id": "E1"}, format="json", HTTP_X_ZARVON_SIGNATURE="INVALID")
        self.assertEqual(bad_wh.status_code, 401)
        ok_wh1 = self.client.post("/api/v1/finance/webhooks/bank/", {"event_id": "E2"}, format="json", HTTP_X_ZARVON_SIGNATURE="valid-sig")
        self.assertEqual(ok_wh1.status_code, 200)
        ok_wh2 = self.client.post("/api/v1/finance/webhooks/bank/", {"event_id": "E2"}, format="json", HTTP_X_ZARVON_SIGNATURE="valid-sig")
        self.assertTrue(ok_wh2.json()["idempotent_replay"])
        self.assertEqual(WebhookEvent.objects.filter(event_id="E2").count(), 1)

        # Maker-Checker: same user cannot approve own request
        mc = MakerCheckerRequest.objects.create(action_type="BHM_UPDATE", target_model="BhmValue", payload={"amount_uzs": 460000}, reason="Update", requested_by=self.super_admin)
        self.client.force_authenticate(user=self.super_admin)
        self.assertEqual(
            self.client.post(f"/api/v1/accounts/maker-checker/{mc.id}/decide/", {"decision": "APPROVED", "decision_note": "Self"}, format="json", HTTP_X_MFA_CODE="123456").status_code,
            403,
        )

    def test_click_prepare_complete_signature_and_settlement(self):
        from django.conf import settings
        from django.utils import timezone
        from apps.finance.psp import compute_click_signature
        from apps.finance.models import CustomerLimit, InstallmentContract, PspTransaction
        from apps.governance.models import SecurityEvent

        CustomerConsent.objects.create(user=self.customer, purpose="IDENTITY", is_granted=True)
        CustomerConsent.objects.create(user=self.customer, purpose="CREDIT_BUREAU", is_granted=True)
        CustomerLimit.objects.update_or_create(user=self.customer, defaults={"total_limit_uzs": 30_000_000, "used_limit_uzs": 0})
        self.client.force_authenticate(user=self.customer)

        order_res = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": f"chk-clk-{uuid.uuid4().hex[:6]}",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 1}],
                "payment_channel": "ZARVON_NASIYA",
                "plan_id": str(self.plan12.id),
            },
            format="json",
        )
        self.assertEqual(order_res.status_code, 201)
        contract_num = order_res.json()["finance"]["contract_number"]
        monthly = order_res.json()["finance"]["monthly_payment"]

        # Tampered Click MD5 signature must fail with -1 and record SecurityEvent
        bad_click = self.client.post(
            "/api/v1/finance/psp/click/",
            {
                "click_trans_id": "998811",
                "service_id": settings.CLICK_SERVICE_ID,
                "merchant_trans_id": contract_num,
                "amount": str(monthly),
                "action": "0",
                "sign_time": "2026-11-14 12:00:00",
                "sign_string": "0" * 32,
            },
            format="json",
        )
        self.assertEqual(bad_click.status_code, 200)
        self.assertEqual(bad_click.json()["error"], -1)
        self.assertTrue(SecurityEvent.objects.filter(event_type="INVALID_CLICK_SIGNATURE").exists())

        # Valid Prepare (action=0) followed by Complete (action=1)
        sign_time = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        prep_sig = compute_click_signature(
            click_trans_id="77001122",
            service_id=settings.CLICK_SERVICE_ID,
            secret_key=settings.CLICK_SECRET_KEY,
            merchant_trans_id=contract_num,
            amount=str(monthly),
            action="0",
            sign_time=sign_time,
        )
        prep = self.client.post(
            "/api/v1/finance/psp/click/",
            {
                "click_trans_id": "77001122",
                "service_id": settings.CLICK_SERVICE_ID,
                "merchant_trans_id": contract_num,
                "amount": str(monthly),
                "action": "0",
                "sign_time": sign_time,
                "sign_string": prep_sig,
            },
            format="json",
        )
        self.assertEqual(prep.json()["error"], 0)
        prep_id = prep.json()["merchant_prepare_id"]

        comp_sig = compute_click_signature(
            click_trans_id="77001122",
            service_id=settings.CLICK_SERVICE_ID,
            secret_key=settings.CLICK_SECRET_KEY,
            merchant_trans_id=contract_num,
            merchant_prepare_id=prep_id,
            amount=str(monthly),
            action="1",
            sign_time=sign_time,
        )
        comp = self.client.post(
            "/api/v1/finance/psp/click/",
            {
                "click_trans_id": "77001122",
                "service_id": settings.CLICK_SERVICE_ID,
                "merchant_trans_id": contract_num,
                "merchant_prepare_id": prep_id,
                "amount": str(monthly),
                "action": "1",
                "sign_time": sign_time,
                "sign_string": comp_sig,
            },
            format="json",
        )
        self.assertEqual(comp.json()["error"], 0)
        tx = PspTransaction.objects.get(psp_provider="Click", external_trans_id="77001122")
        self.assertEqual(tx.action_stage, "PERFORMED")
        self.assertEqual(tx.state_code, 2)
        c = InstallmentContract.objects.get(contract_number=contract_num)
        self.assertLess(c.remaining_balance, c.total_payable)

    def test_payme_jsonrpc_auth_and_perform(self):
        import base64
        from django.conf import settings
        from apps.commerce.models import Order, OrderStatus
        from apps.finance.models import PspTransaction

        self.client.force_authenticate(user=self.customer)
        ord_res = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": f"chk-pm-{uuid.uuid4().hex[:6]}",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 1}],
                "payment_channel": "DIRECT_PAY",
                "psp_provider": "Payme",
            },
            format="json",
        )
        self.assertEqual(ord_res.status_code, 201)
        order_num = ord_res.json()["order_number"]
        order = Order.objects.get(order_number=order_num)
        order.status = OrderStatus.AWAITING_FINANCE
        order.save(update_fields=["status"])

        # Missing Basic Auth -> JSON-RPC -32504
        unauth = self.client.post(
            "/api/v1/finance/psp/payme/",
            {"jsonrpc": "2.0", "id": 1, "method": "CheckPerformTransaction", "params": {"amount": 100000, "account": {"order_id": order_num}}},
            format="json",
        )
        self.assertEqual(unauth.json()["error"]["code"], -32504)

        auth_hdr = "Basic " + base64.b64encode(f"Paycom:{settings.PAYME_CASHBOX_KEY}".encode("utf-8")).decode("utf-8")
        # Wrong amount -> -31001
        bad_amt = self.client.post(
            "/api/v1/finance/psp/payme/",
            {"jsonrpc": "2.0", "id": 2, "method": "CheckPerformTransaction", "params": {"amount": 12300, "account": {"order_id": order_num}}},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertEqual(bad_amt.json()["error"]["code"], -31001)

        tiyin = order.total_amount * 100
        ok_chk = self.client.post(
            "/api/v1/finance/psp/payme/",
            {"jsonrpc": "2.0", "id": 3, "method": "CheckPerformTransaction", "params": {"amount": tiyin, "account": {"order_id": order_num}}},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertTrue(ok_chk.json()["result"]["allow"])

        cr = self.client.post(
            "/api/v1/finance/psp/payme/",
            {"jsonrpc": "2.0", "id": 4, "method": "CreateTransaction", "params": {"id": "pm_test_101", "amount": tiyin, "account": {"order_id": order_num}}},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertEqual(cr.json()["result"]["state"], 1)

        pf = self.client.post(
            "/api/v1/finance/psp/payme/",
            {"jsonrpc": "2.0", "id": 5, "method": "PerformTransaction", "params": {"id": "pm_test_101"}},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertEqual(pf.json()["result"]["state"], 2)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        self.assertTrue(PspTransaction.objects.filter(psp_provider="Payme", external_trans_id="pm_test_101", state_code=2).exists())

    def test_katm_mib_inn_dsti_and_sandbox_demo_switch(self):
        from django.test import override_settings
        from apps.finance.models import ExternalScoringReport

        # Sandbox demo role switch must work even when DEBUG=False (Render live config)
        with override_settings(DEBUG=False, ZARVON_SANDBOX_MODE=True):
            sw = self.client.post("/api/v1/auth/demo-switch/", {"phone": self.customer.phone}, format="json")
            self.assertEqual(sw.status_code, 200)
            self.assertEqual(sw.json()["user"]["phone"], self.customer.phone)
            me = self.client.get("/api/v1/auth/me/")
            self.assertTrue(me.json()["authenticated"])

        CustomerConsent.objects.create(user=self.customer, purpose="IDENTITY", is_granted=True)
        CustomerConsent.objects.create(user=self.customer, purpose="CREDIT_BUREAU", is_granted=True)
        self.client.force_authenticate(user=self.customer)

        # Invalid 8-digit INN rejected
        bad_inn = self.client.post(
            "/api/v1/finance/kyc/verify/",
            {"pinfl": "31405940010012", "inn": "12345678", "passport": "AD1234567", "birth_year": 1994, "liveness_passed": True},
            format="json",
        )
        self.assertEqual(bad_inn.status_code, 400)

        # MIB debt scenario -> BLOCKED & DECLINE
        mib_res = self.client.post(
            "/api/v1/finance/kyc/verify/",
            {"pinfl": "31405940010088", "inn": "305112849", "passport": "AD1234567", "birth_year": 1994, "monthly_income_uzs": 9_000_000, "scenario": "mib_debt", "liveness_passed": True},
            format="json",
        )
        self.assertEqual(mib_res.status_code, 200)
        self.assertEqual(mib_res.json()["decision"], "DECLINE")
        self.assertEqual(mib_res.json()["scoring_report"]["mib_status"], "BLOCKED")
        self.assertGreater(mib_res.json()["scoring_report"]["mib_debt_uzs"], 0)

        # High DSTI > 50% -> DECLINE
        dsti_res = self.client.post(
            "/api/v1/finance/kyc/verify/",
            {"pinfl": "31405940010077", "inn": "305112849", "passport": "AD1234567", "birth_year": 1994, "monthly_income_uzs": 5_000_000, "scenario": "high_debt", "liveness_passed": True},
            format="json",
        )
        self.assertEqual(dsti_res.status_code, 200)
        self.assertEqual(dsti_res.json()["decision"], "DECLINE")
        self.assertGreaterEqual(dsti_res.json()["scoring_report"]["dsti_before_pct"], 50.0)

        # Clean scenario -> APPROVE + masked INN saved
        clean_res = self.client.post(
            "/api/v1/finance/kyc/verify/",
            {"pinfl": "31405940010012", "inn": "305112849", "passport": "AD1234567", "birth_year": 1994, "monthly_income_uzs": 12_000_000, "scenario": "clean", "liveness_passed": True},
            format="json",
        )
        self.assertEqual(clean_res.status_code, 200)
        self.assertEqual(clean_res.json()["decision"], "APPROVE")
        self.assertEqual(clean_res.json()["scoring_report"]["inn_masked"], "305****49")
        self.assertGreaterEqual(ExternalScoringReport.objects.filter(user=self.customer).count(), 3)

    def test_payment_cards_and_due_monitor_reminders(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.finance.models import CustomerLimit, InstallmentContract, PaymentCard, PaymentReminderLog

        # Masked PaymentCard vault check
        self.client.force_authenticate(user=self.customer)
        c_res = self.client.post(
            "/api/v1/finance/cards/",
            {"card_number": "8600 1234 5678 9012", "expiry": "08/28", "provider": "Payme"},
            format="json",
        )
        self.assertEqual(c_res.status_code, 201)
        card = c_res.json()["card"]
        self.assertEqual(card["card_brand"], "Uzcard")
        self.assertEqual(card["card_masked_pan"], "8600 **** **** 9012")
        self.assertNotIn("12345678", str(c_res.json()))
        self.assertTrue(PaymentCard.objects.filter(user=self.customer).exists())

        # Create contract with due item in 2 days -> Due Monitor detects + sends SMS reminder
        CustomerConsent.objects.create(user=self.customer, purpose="IDENTITY", is_granted=True)
        CustomerConsent.objects.create(user=self.customer, purpose="CREDIT_BUREAU", is_granted=True)
        CustomerLimit.objects.update_or_create(user=self.customer, defaults={"total_limit_uzs": 30_000_000, "used_limit_uzs": 0})
        chk = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": f"chk-due-{uuid.uuid4().hex[:6]}",
                "items": [{"product_id": str(self.prod_a.id), "quantity": 1}],
                "payment_channel": "ZARVON_NASIYA",
                "plan_id": str(self.plan12.id),
            },
            format="json",
        )
        c_num = chk.json()["finance"]["contract_number"]
        contract = InstallmentContract.objects.get(contract_number=c_num)
        due_item = contract.schedule_items.first()
        due_item.due_date = timezone.localdate() + timedelta(days=2)
        due_item.save(update_fields=["due_date"])

        # Customer cabinet shows due_alerts countdown
        cab = self.client.get("/api/v1/finance/cabinet/")
        self.assertEqual(cab.status_code, 200)
        self.assertTrue(any(a["days_until_due"] == 2 and a["contract_number"] == c_num for a in cab.json()["due_alerts"]))

        # Operations due-monitor lists and sends reminder
        self.client.force_authenticate(user=self.super_admin)
        dm_get = self.client.get("/api/v1/finance/due-monitor/")
        self.assertEqual(dm_get.status_code, 200)
        self.assertGreaterEqual(dm_get.json()["summary"]["due_3_days_count"], 1)

        dm_post = self.client.post(
            "/api/v1/finance/due-monitor/",
            {"action": "send_one", "schedule_item_id": str(due_item.id), "channel": "SMS"},
            format="json",
        )
        self.assertEqual(dm_post.status_code, 200)
        self.assertEqual(dm_post.json()["sent_count"], 1)
        self.assertTrue(PaymentReminderLog.objects.filter(schedule_item=due_item, channel="SMS").exists())


# --- Added Verification Tests: Uzum Bank Merchant API, PSP URLs, Cart Stepper & Banners ---
import base64 as _test_base64
from django.core.management import call_command as _test_call_command
from django.test import TestCase as _DjangoTestCase
from django.conf import settings as _test_settings
from rest_framework.test import APIClient as _TestAPIClient
from apps.accounts.models import User as _TestUser
from apps.catalog.models import Product as _TestProduct, ProductStatus as _TestProductStatus
from apps.finance.models import PspTransaction as _TestPspTransaction
from apps.finance.psp import build_psp_checkout_payload as _build_psp_checkout_payload
from apps.governance.models import SecurityEvent as _TestSecurityEvent


class UzumPspAndMarketplaceFlowTests(_DjangoTestCase):
    @classmethod
    def setUpTestData(cls):
        _test_call_command("seed_zarvon")

    def setUp(self):
        self.client = _TestAPIClient()
        self.customer = _TestUser.objects.get(phone="+998901110001")
        self.client.force_authenticate(user=self.customer)
        self.product = _TestProduct.objects.filter(installment_eligible=True, status=_TestProductStatus.APPROVED).first()

    def test_uzum_merchant_api_auth_and_three_stage_settlement(self):
        # 1. Create a DIRECT_PAY order via CheckoutView
        chk = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "idempotency_key": f"uzm-chk-{self.product.id}",
                "delivery_type": "COURIER",
                "delivery_address": "Toshkent, Chilonzor 5",
                "payment_channel": "DIRECT_PAY",
                "psp_provider": "Uzum Bank",
                "items": [{"product_id": str(self.product.id), "quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(chk.status_code, 201, chk.content)
        order_num = chk.data["order_number"]
        total_uzs = int(chk.data["total_amount"])
        self.assertEqual(total_uzs, self.product.cash_price)
        self.assertIn("psp_checkout", chk.data["finance"])
        self.assertIn("apelsin.uz", chk.data["finance"]["psp_checkout"]["checkout_url"])

        # 2. Invalid Basic Auth must return 401 and log a HIGH SecurityEvent
        bad_res = self.client.post(
            "/api/v1/finance/psp/uzum/check/",
            {"serviceId": _test_settings.UZUM_SERVICE_ID, "params": {"orderId": order_num}},
            format="json",
            HTTP_AUTHORIZATION="Basic d3Jvbmc6d3Jvbmc=",
        )
        self.assertEqual(bad_res.status_code, 401)
        self.assertEqual(bad_res.data["errorCode"], "10001")
        self.assertTrue(_TestSecurityEvent.objects.filter(event_type="PSP_UZUM_AUTH_FAILED").exists())

        # 3. Valid Basic Auth: /check -> /create -> /confirm -> /status
        creds = f"{_test_settings.UZUM_SERVICE_ID}:{_test_settings.UZUM_SECRET_KEY}"
        auth_hdr = "Basic " + _test_base64.b64encode(creds.encode("utf-8")).decode("ascii")
        tiyin = total_uzs * 100
        tx_id = "uzm-test-0001"

        r_check = self.client.post(
            "/api/v1/finance/psp/uzum/check/",
            {"serviceId": _test_settings.UZUM_SERVICE_ID, "params": {"orderId": order_num}},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertEqual(r_check.status_code, 200)
        self.assertEqual(r_check.data["status"], "OK")
        self.assertEqual(r_check.data["data"]["expected_amount_tiyin"], tiyin)

        r_create = self.client.post(
            "/api/v1/finance/psp/uzum/create/",
            {"serviceId": _test_settings.UZUM_SERVICE_ID, "transId": tx_id, "amount": tiyin, "params": {"orderId": order_num}},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertEqual(r_create.status_code, 200)
        self.assertEqual(r_create.data["status"], "CREATED")

        r_confirm = self.client.post(
            "/api/v1/finance/psp/uzum/confirm/",
            {"serviceId": _test_settings.UZUM_SERVICE_ID, "transId": tx_id},
            format="json",
            HTTP_AUTHORIZATION=auth_hdr,
        )
        self.assertEqual(r_confirm.status_code, 200)
        self.assertEqual(r_confirm.data["status"], "CONFIRMED")

        tx_obj = _TestPspTransaction.objects.get(external_trans_id=tx_id)
        self.assertEqual(tx_obj.state_code, 2)
        self.assertEqual(tx_obj.action_stage, "PERFORMED")
        self.assertEqual(tx_obj.amount_tiyin, tiyin)

        # 4. PspCheckoutAndSimulatorView executes 3-step Uzum Bank protocol & returns links
        sim = self.client.post(
            "/api/v1/finance/psp/checkout/",
            {"reference": order_num, "psp_provider": "Uzum Bank", "amount_uzs": total_uzs},
            format="json",
        )
        self.assertEqual(sim.status_code, 200)
        self.assertEqual(len(sim.data["trace"]), 3)
        self.assertIn("checkout_url", sim.data)
        self.assertIn("payme", sim.data["links"])
        self.assertIn("click", sim.data["links"])

    def test_psp_checkout_payload_urls(self):
        payme = _build_psp_checkout_payload(psp_provider="Payme", reference="ZRV-999", amount_uzs=150000)
        self.assertIn("paycom.uz/", payme["checkout_url"])
        self.assertEqual(payme["amount_tiyin"], 15000000)

        click = _build_psp_checkout_payload(psp_provider="Click", reference="ZRV-999", amount_uzs=150000)
        self.assertIn("my.click.uz/services/pay", click["checkout_url"])
        self.assertIn("transaction_param=ZRV-999", click["checkout_url"])

    def test_cart_inline_stepper_delta_and_home_ux_payload(self):
        # Clear cart then increment twice and decrement twice -> deleted at 0
        self.client.delete("/api/v1/commerce/cart/")
        r1 = self.client.post("/api/v1/commerce/cart/", {"product_id": str(self.product.id), "delta": 1}, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["items"][0]["quantity"], 1)

        r2 = self.client.post("/api/v1/commerce/cart/", {"product_id": str(self.product.id), "delta": 1}, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["items"][0]["quantity"], 2)

        r3 = self.client.post("/api/v1/commerce/cart/", {"product_id": str(self.product.id), "delta": -1}, format="json")
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.data["items"][0]["quantity"], 1)

        r4 = self.client.post("/api/v1/commerce/cart/", {"product_id": str(self.product.id), "delta": -1}, format="json")
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(len(r4.data["items"]), 0)

        # Home payload includes >= 3 carousel banners and delivery_badge on cards
        home = self.client.get("/api/v1/catalog/home/")
        self.assertEqual(home.status_code, 200)
        self.assertGreaterEqual(len(home.data["banners"]), 3)
        self.assertEqual(home.data["banners"][0]["title"], "Kerakli mahsulot — qulay to‘lov bilan")
        self.assertIn("bank_partners", home.data)
        self.assertGreaterEqual(len(home.data["bank_partners"]), 1)
        self.assertTrue(all("delivery_badge" in p for p in home.data["new_arrivals"]))
        self.assertTrue(
            all(p["primary_image"].startswith("/static/img/products/") for p in home.data["new_arrivals"])
        )

    def test_seller_product_image_upload_sanitize_and_rbac_serve(self):
        from pathlib import Path
        from PIL import Image
        from django.conf import settings

        buf = io.BytesIO()
        Image.new("RGBA", (80, 60), (20, 40, 80, 200)).save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Customer cannot upload seller product photos
        forbidden = self.client.post(
            "/api/v1/sellers/my-products/upload-image/",
            {"image": SimpleUploadedFile("bad.png", png_bytes, content_type="image/png")},
            format="multipart",
        )
        self.assertEqual(forbidden.status_code, 403)

        # Authenticate as the product's store owner
        seller_owner = self.product.store.owner
        self.client.force_authenticate(user=seller_owner)

        # Invalid binary rejected cleanly with 400
        bad_file = self.client.post(
            "/api/v1/sellers/my-products/upload-image/",
            {"image": SimpleUploadedFile("corrupt.jpg", b"not-an-image", content_type="image/jpeg")},
            format="multipart",
        )
        self.assertEqual(bad_file.status_code, 400)

        # Valid RGBA PNG sanitized to JPEG, attached to product, and served at /media-public/
        ok_resp = self.client.post(
            "/api/v1/sellers/my-products/upload-image/",
            {
                "image": SimpleUploadedFile("studio.png", png_bytes, content_type="image/png"),
                "product_id": str(self.product.id),
            },
            format="multipart",
        )
        self.assertEqual(ok_resp.status_code, 201)
        img_url = ok_resp.data["image_url"]
        self.assertTrue(img_url.startswith("/media-public/products/"))

        saved_rel = img_url.replace("/media-public/", "", 1)
        saved_disk_path = Path(settings.MEDIA_ROOT) / saved_rel
        try:
            serve_resp = self.client.get(img_url)
            self.assertEqual(serve_resp.status_code, 200)
            body = b"".join(serve_resp.streaming_content)
            self.assertGreater(len(body), 100)
            serve_resp.close()

            trav = self.client.get("/media-public/../config/settings.py")
            self.assertEqual(trav.status_code, 404)
        finally:
            if saved_disk_path.exists():
                saved_disk_path.unlink()

    def test_phone_lookup_masked_identity_normalization_and_validation(self):
        self.client.force_authenticate(user=None)

        found = self.client.post("/api/v1/auth/phone-lookup/", {"phone": "90 111 00 01"}, format="json")
        self.assertEqual(found.status_code, 200)
        self.assertTrue(found.data["exists"])
        self.assertEqual(found.data["normalized_phone"], "+998901110001")
        self.assertIn("*", found.data["masked_name"])
        self.assertNotEqual(found.data["masked_name"], self.customer.full_name)

        missing = self.client.post("/api/v1/auth/phone-lookup/", {"phone": "+998 99 888 77 66"}, format="json")
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(missing.data["exists"])
        self.assertEqual(missing.data["normalized_phone"], "+998998887766")
        self.assertIsNone(missing.data["masked_name"])

        invalid = self.client.post("/api/v1/auth/phone-lookup/", {"phone": "123"}, format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_delivery_points_bts_search_and_custom_create(self):
        # Seeded nationwide BTS points searchable publicly
        bts_list = self.client.get("/api/v1/commerce/delivery-points/?q=BTS")
        self.assertEqual(bts_list.status_code, 200)
        self.assertGreaterEqual(len(bts_list.data["results"]), 5)
        self.assertTrue(any("BTS" in pt["name"] for pt in bts_list.data["results"]))

        furqat = self.client.get("/api/v1/commerce/delivery-points/?q=Furqat")
        self.assertEqual(furqat.status_code, 200)
        self.assertGreaterEqual(len(furqat.data["results"]), 1)

        # Anonymous user cannot create a custom delivery point
        self.client.force_authenticate(user=None)
        anon_post = self.client.post(
            "/api/v1/commerce/delivery-points/",
            {"name": "BTS Custom", "region": "Samarqand", "address": "Registon 1"},
            format="json",
        )
        self.assertIn(anon_post.status_code, (401, 403))

        # Authenticated user can add a custom BTS / PVZ pickup location
        self.client.force_authenticate(user=self.customer)
        created = self.client.post(
            "/api/v1/commerce/delivery-points/",
            {"name": "BTS Express — Test Hub", "region": "Farg‘ona", "address": "Navoiy ko‘chasi 12"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.data["ok"])
        self.assertEqual(created.data["point"]["name"], "BTS Express — Test Hub")

        search_created = self.client.get("/api/v1/commerce/delivery-points/?q=Test Hub")
        self.assertEqual(search_created.status_code, 200)
        self.assertEqual(len(search_created.data["results"]), 1)

    def test_product_detail_returns_similar_products(self):
        detail = self.client.get(f"/api/v1/catalog/products/{self.product.slug}/")
        self.assertEqual(detail.status_code, 200)
        sim = detail.data.get("similar_products", [])
        self.assertGreaterEqual(len(sim), 1)
        self.assertLessEqual(len(sim), 4)
        self.assertTrue(all(str(x["id"]) != str(self.product.id) for x in sim))

    def test_credit_condition_cash_only_policy_and_supervisor_alerts(self):
        from apps.accounts.models import UserRole as _Role
        from apps.finance.models import CustomerConsent as _Consent, InstallmentPlan as _Plan
        from apps.governance.models import NotificationEvent as _Notif

        super_admin = _TestUser.objects.filter(role=_Role.SUPER_ADMIN, is_active=True).first()
        auditor = _TestUser.objects.filter(role=_Role.AUDITOR, is_active=True).first()
        plan12 = _Plan.objects.filter(months=12, is_active=True).first()
        self.assertIsNotNone(super_admin)
        self.assertIsNotNone(auditor)
        self.assertIsNotNone(plan12)

        clean_cust = _TestUser.objects.create_user(
            "+998901999001",
            "Pass1234!",
            full_name="Toza Mijoz",
            role=_Role.CUSTOMER,
        )
        self.client.force_authenticate(user=clean_cust)
        c_res = self.client.post(
            "/api/v1/finance/consents/",
            {"purposes": {"IDENTITY": True, "CREDIT_BUREAU": True, "BANK_TRANSFER": True}},
            format="json",
        )
        self.assertEqual(c_res.status_code, 200, c_res.data)

        # 1. Clean history (0 credits, 0 overdue) -> Nasiya open + supervisor notified
        clean_res = self.client.post(
            "/api/v1/finance/kyc/verify/",
            {
                "pinfl": "31908950010991",
                "inn": "309998811",
                "passport": "AA1234567",
                "birth_year": 1995,
                "monthly_income_uzs": 9_500_000,
                "scenario": "clean",
                "liveness_passed": True,
            },
            format="json",
        )
        self.assertEqual(clean_res.status_code, 200, clean_res.data)
        self.assertEqual(clean_res.data["decision"], "APPROVE")
        self.assertFalse(clean_res.data["credit_policy"]["cash_only_required"])
        self.assertEqual(clean_res.data["credit_policy"]["credit_condition_code"], "CLEAN_NO_CREDIT")
        self.assertGreaterEqual(clean_res.data["supervisors_notified"], 1)
        self.assertTrue(
            _Notif.objects.filter(
                user=super_admin,
                correlation_id__startswith="SUP-CREDIT:CLEAN_NO_CREDIT:",
            ).exists()
        )

        # 2. Active external credit -> Cash-Only enforced across Scoring, Cart & Checkout
        mod_res = self.client.post(
            "/api/v1/finance/kyc/verify/",
            {
                "pinfl": "31908950010991",
                "inn": "309998811",
                "passport": "AA1234567",
                "birth_year": 1995,
                "monthly_income_uzs": 9_500_000,
                "scenario": "moderate_credit",
                "liveness_passed": True,
            },
            format="json",
        )
        self.assertEqual(mod_res.status_code, 200, mod_res.data)
        self.assertEqual(mod_res.data["decision"], "DECLINE")
        self.assertTrue(mod_res.data["credit_policy"]["cash_only_required"])
        self.assertEqual(mod_res.data["credit_policy"]["credit_condition_code"], "ACTIVE_CREDIT_CASH_ONLY")

        self.client.post(
            "/api/v1/commerce/cart/",
            {"product_id": str(self.product.id), "quantity": 1},
            format="json",
        )
        cart_res = self.client.get("/api/v1/commerce/cart/")
        self.assertEqual(cart_res.status_code, 200)
        self.assertTrue(cart_res.data["cash_only_required"])
        self.assertFalse(cart_res.data["installment_eligible"])

        nasiya_blk = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "delivery_type": "COURIER",
                "delivery_address": "Toshkent, Chilonzor",
                "payment_channel": "ZARVON_NASIYA",
                "plan_id": str(plan12.id),
                "months": 12,
                "down_payment": 0,
            },
            format="json",
        )
        self.assertEqual(nasiya_blk.status_code, 403, nasiya_blk.data)
        self.assertTrue(nasiya_blk.data["cash_only_required"])

        bank_blk = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "delivery_type": "COURIER",
                "delivery_address": "Toshkent, Chilonzor",
                "payment_channel": "BANK_GATEWAY",
                "months": 12,
            },
            format="json",
        )
        self.assertEqual(bank_blk.status_code, 403, bank_blk.data)
        self.assertTrue(
            _TestSecurityEvent.objects.filter(
                user=clean_cust,
                event_type="CREDIT_POLICY_ACTIVE_CREDIT_CASH_ONLY",
            ).exists()
        )

        # DIRECT_PAY (Naqd / Click / Payme / Uzum / Karta) remains allowed!
        direct_ok = self.client.post(
            "/api/v1/commerce/checkout/",
            {
                "delivery_type": "COURIER",
                "delivery_address": "Toshkent, Chilonzor",
                "payment_channel": "DIRECT_PAY",
                "psp_provider": "Payme",
            },
            format="json",
        )
        self.assertEqual(direct_ok.status_code, 201, direct_ok.data)

        # 3. Supervisor inspection & Auditor read-only RBAC
        self.client.force_authenticate(user=auditor)
        aud_get = self.client.get("/api/v1/finance/scoring-reports/")
        self.assertEqual(aud_get.status_code, 200)
        self.assertGreaterEqual(len(aud_get.data["supervisor_alerts"]), 1)
        self.assertGreaterEqual(aud_get.data["summary"]["cash_only_customers"], 1)
        aud_post = self.client.post(
            "/api/v1/finance/scoring-reports/",
            {"user_id": str(clean_cust.id), "scenario": "overdue_katm", "refresh_bureau": True},
            format="json",
        )
        self.assertEqual(aud_post.status_code, 403)

        self.client.force_authenticate(user=super_admin)
        sup_post = self.client.post(
            "/api/v1/finance/scoring-reports/",
            {"user_id": str(clean_cust.id), "scenario": "overdue_katm", "refresh_bureau": True},
            format="json",
        )
        self.assertEqual(sup_post.status_code, 200, sup_post.data)
        self.assertTrue(sup_post.data["ok"])
        self.assertTrue(sup_post.data["credit_policy"]["cash_only_required"])
        self.assertEqual(sup_post.data["credit_policy"]["credit_condition_code"], "OVERDUE_BLOCKED")
        self.assertGreaterEqual(sup_post.data["supervisors_notified"], 1)
