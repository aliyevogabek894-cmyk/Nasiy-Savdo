"""Seed comprehensive realistic Uzbek Sandbox/Demo data for ZARVON Marketplace & Nasiya."""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import MakerCheckerRequest, Profile, User, UserRole
from apps.catalog.models import Banner, Brand, Category, Product, ProductImage, ProductStatus, PromoCode, Review
from apps.commerce.models import DeliveryPoint, Order, OrderItem, OrderStatus, SellerOrder, Shipment
from apps.finance.models import (
    BankPartner,
    ContractStatus,
    CustomerConsent,
    CustomerLimit,
    InstallmentContract,
    InstallmentPlan,
    InstallmentScheduleItem,
    LimitEvent,
    PaymentRecord,
    ReconciliationRecord,
)
from apps.finance.providers import OwnInstallmentProvider
from apps.governance.models import AuditLog, BhmValue, ComplianceRuleVersion, NotificationEvent, SecurityEvent
from apps.inventory.models import StockLevel, StockMovement, Warehouse
from apps.risk_collections.models import (
    CollectionAction,
    CollectionCase,
    FraudCase,
    FraudSignal,
    RestructuringCase,
    RiskAssessment,
    SupportTicket,
)
from apps.sellers.models import SellerApplication, SellerInvitation, SellerOnboardingStatus, SellerStaff, Store


class Command(BaseCommand):
    help = "Populate ZARVON platform with realistic Sandbox/Demo marketplace, nasiya, seller & admin data"

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(phone="+998901110001").exists():
            self._ensure_v2_samples()
            self.stdout.write(self.style.WARNING("Ma'lumotlar bazasi allaqachon to‘ldirilgan (v2 namunalar tekshirildi)."))
            return

        # 1. Governance & Statutory Compliance
        bhm = BhmValue.objects.create(
            amount_uzs=440_000,
            effective_from=timezone.now().date(),
            is_active=True,
            note="2026-yil amaldagi BHM (110 mln so‘m = 250 BHM chegarasi uchun)",
        )
        rule = ComplianceRuleVersion.get_active()

        # 2. Users for ALL roles
        def mk_user(phone, name, role, pwd="Zarvon2026!", mfa=False, kyc="UNVERIFIED", pinfl="", passport=""):
            u = User.objects.create_user(
                phone=phone,
                password=pwd,
                full_name=name,
                role=role,
                is_phone_verified=True,
                mfa_enabled=mfa,
                kyc_status=kyc,
                is_staff=(role == UserRole.SUPER_ADMIN),
                is_superuser=(role == UserRole.SUPER_ADMIN),
            )
            if pinfl:
                u.set_identity_fields(pinfl=pinfl, passport=passport)
                u.birth_year = 1994
                u.save()
            Profile.objects.create(user=u, region="Toshkent shahri", address="Chilonzor tumani, Bunyodkor 15")
            return u

        customer = mk_user("+998901110001", "Azizbek Karimov", UserRole.CUSTOMER, kyc="VERIFIED", pinfl="31405940010012", passport="AD1234567")
        customer_new = mk_user("+998901110002", "Malika Tursunova", UserRole.CUSTOMER, kyc="UNVERIFIED")
        seller_owner_1 = mk_user("+998902220001", "Sardor Alimov (TexnoUz)", UserRole.SELLER_OWNER, mfa=True)
        seller_staff_1 = mk_user("+998902220002", "Dilshod Xasanov (Xodim)", UserRole.SELLER_STAFF)
        seller_owner_2 = mk_user("+998902220003", "Jahongir Raximov (Olmazor)", UserRole.SELLER_OWNER, mfa=True)

        super_admin = mk_user("+998909990001", "Bobur Mansurov (Super Admin)", UserRole.SUPER_ADMIN, mfa=True)
        mkt_admin = mk_user("+998909990002", "Nilufar Saidova (Marketplace)", UserRole.MARKETPLACE_ADMIN, mfa=True)
        fin_officer = mk_user("+998909990003", "Jasur Qodirov (Finance)", UserRole.FINANCE_OFFICER, mfa=True)
        risk_mgr = mk_user("+998909990004", "Shohruh Nazarov (Risk)", UserRole.RISK_MANAGER, mfa=True)
        coll_agent = mk_user("+998909990005", "Umidbek Jo‘rayev (Undirish)", UserRole.COLLECTIONS_AGENT)
        fraud_analyst = mk_user("+998909990006", "Kamola Ergasheva (Fraud)", UserRole.FRAUD_ANALYST, mfa=True)
        content_mgr = mk_user("+998909990007", "Madina Toshmatova (CMS)", UserRole.CONTENT_MANAGER)
        auditor = mk_user("+998909990008", "Rustam Abdullayev (Auditor)", UserRole.AUDITOR, mfa=True)

        # 3. Installment Plans (Strictly compliant <=12 months, <=50%/year)
        p3 = InstallmentPlan.objects.create(name="3 oylik qulay reja", months=3, annual_markup_pct=16.0, commission_pct=1.0, compliance_version=rule)
        p6 = InstallmentPlan.objects.create(name="6 oylik standart reja", months=6, annual_markup_pct=22.0, commission_pct=1.5, compliance_version=rule)
        p9 = InstallmentPlan.objects.create(name="9 oylik muvozanatli reja", months=9, annual_markup_pct=26.0, commission_pct=2.0, compliance_version=rule)
        p12 = InstallmentPlan.objects.create(name="12 oylik maksimal reja", months=12, annual_markup_pct=28.0, commission_pct=2.0, compliance_version=rule)

        # 4. Bank Partners (Sandbox)
        BankPartner.objects.create(name="Hamkor Bank (Sandbox)", code="HAMKOR", environment="SANDBOX", adapter_status="ONLINE", uptime_pct=99.8, avg_latency_ms=340, base_annual_rate_pct=26.0, max_months=12)
        BankPartner.objects.create(name="Ipak Yo‘li Banki (Sandbox)", code="IPAK", environment="SANDBOX", adapter_status="ONLINE", uptime_pct=99.4, avg_latency_ms=480, base_annual_rate_pct=29.0, max_months=12)
        BankPartner.objects.create(name="Asakabank Gateway (Sandbox)", code="ASAKA", environment="SANDBOX", adapter_status="DEGRADED", uptime_pct=97.9, avg_latency_ms=1120, base_annual_rate_pct=27.5, max_months=12)

        # 5. Customer Limits & Consents
        lim = CustomerLimit.objects.create(user=customer, tier="Plus", total_limit_uzs=25_000_000, used_limit_uzs=4_200_000, is_demo_limit=True)
        LimitEvent.objects.create(customer_limit=lim, event_type="INITIAL", amount_delta=25_000_000, reason="MyID tasdiqlandi — Plus daraja (DEMO)", actor=fin_officer)
        CustomerLimit.objects.create(user=customer_new, tier="Start", total_limit_uzs=5_000_000, used_limit_uzs=0, is_demo_limit=True)

        for p_purpose in ("IDENTITY", "CREDIT_BUREAU", "BANK_TRANSFER"):
            CustomerConsent.objects.create(user=customer, purpose=p_purpose, is_granted=True)

        RiskAssessment.objects.create(
            user=customer,
            model_version="risk-score-v2.1-uz",
            score=752,
            dti_ratio_pct=19.4,
            decision="APPROVE",
            reason_codes=["MYID_VERIFIED", "TIMELY_REPAYMENT_HISTORY", "LOW_DTI"],
            recommended_tier="Plus",
        )

        # 6. Stores, Staff & Pending Onboarding Application
        store1 = Store.objects.create(
            owner=seller_owner_1,
            legal_name="«TEXNO UZ SAVDO» MChJ",
            public_name="TexnoUz Premium",
            slug="texnouz-premium",
            description="Rasmiy kafolatli smartfonlar, noutbuklar va aqlli elektronika do‘koni.",
            logo_text="TU",
            official_phone="+998712001122",
            official_email="sales@texnouz.uz",
            legal_address="Toshkent sh., Malika savdo majmuasi A-12",
            return_address="Toshkent sh., Shayxontohur tumani, Navoiy 24",
            delivery_regions=["Toshkent", "Samarqand", "Farg‘ona", "Buxoro"],
            commission_pct=7.0,
            holdback_pct=10.0,
            rating=4.9,
        )
        store1.bank_account_encrypted = ""
        store1.save()
        wh1 = Warehouse.objects.create(store=store1, name="Toshkent Markaziy Ombor", region="Toshkent", address="Navoiy 24")
        SellerStaff.objects.create(store=store1, user=seller_staff_1, position_title="Katalog va buyurtma operatori", allowed_sections=["products", "orders", "inventory"])

        store2 = Store.objects.create(
            owner=seller_owner_2,
            legal_name="«OLMAZOR UY-RO‘ZG‘OR» MChJ",
            public_name="Olmazor Texnika & Mebel",
            slug="olmazor-texnika",
            description="Maishiy texnika, televizorlar va zamonaviy uy mebellari.",
            logo_text="OM",
            official_phone="+998712003344",
            official_email="info@olmazormebel.uz",
            legal_address="Toshkent sh., Olmazor tumani, Farobiy 8",
            return_address="Toshkent sh., Olmazor tumani, Farobiy 8",
            delivery_regions=["Toshkent", "Toshkent viloyati", "Andijon", "Namangan"],
            commission_pct=8.5,
            holdback_pct=12.0,
            rating=4.7,
        )
        wh2 = Warehouse.objects.create(store=store2, name="Olmazor Ombori", region="Toshkent", address="Farobiy 8")

        SellerInvitation.issue_invitation(
            company_name="Baraka Elektronika MChJ",
            target_phone="+998905556677",
            target_email="partner@baraka.uz",
            expires_hours=72,
            created_by=mkt_admin,
        )
        SellerApplication.objects.create(
            legal_name="«SAMARQAND NUR SAVDO» MChJ",
            public_name="Samarqand Tech",
            entity_type="MChJ",
            stir_number="308124599",
            representative_name="Otabek Nurmatov",
            official_phone="+998915550199",
            official_email="info@samtech.uz",
            legal_address="Samarqand sh., Amir Temur 42",
            return_address="Samarqand sh., Amir Temur 42",
            product_categories=["Televizorlar", "Maishiy texnika"],
            delivery_regions=["Samarqand", "Jizzax", "Navoiy"],
            terms_accepted_at=timezone.now(),
            status=SellerOnboardingStatus.SUBMITTED,
        )

        # 7. Categories & Brands
        c_phone = Category.objects.create(name="Smartfonlar", name_ru="Смартфоны", name_en="Smartphones", slug="smartfonlar", icon_name="smartphone", sort_order=1, attribute_schema=["Xotira", "Ekran", "Kamera", "Batareya"])
        c_laptop = Category.objects.create(name="Noutbuklar", name_ru="Ноутбуки", name_en="Laptops", slug="noutbuklar", icon_name="laptop", sort_order=2, attribute_schema=["Protsessor", "RAM", "SSD", "Ekran"])
        c_tv = Category.objects.create(name="Televizorlar", name_ru="Телевизоры", name_en="TVs", slug="televizorlar", icon_name="tv", sort_order=3, attribute_schema=["Diagonal", "Matritsa", "Ruxsat"])
        c_fridge = Category.objects.create(name="Sovutgichlar", name_ru="Холодильники", name_en="Refrigerators", slug="sovutgichlar", icon_name="fridge", sort_order=4, attribute_schema=["Hajm", "Energiya sinfi", "No Frost"])
        c_washer = Category.objects.create(name="Kir yuvish mashinalari", name_ru="Стиральные машины", name_en="Washers", slug="kir-yuvish", icon_name="washer", sort_order=5, attribute_schema=["Sig‘im", "Aylanish", "Inverter"])
        c_mebel = Category.objects.create(name="Mebel", name_ru="Мебель", name_en="Furniture", slug="mebel", icon_name="sofa", sort_order=6, attribute_schema=["Material", "O‘lcham", "Rang"])
        c_realty = Category.objects.create(
            name="Ko‘chmas mulk (Naqd)",
            name_ru="Недвижимость",
            name_en="Real Estate",
            slug="kochmas-mulk",
            icon_name="home",
            installment_allowed=False,
            prohibition_note="27.1-bo‘lim: Ko‘chmas mulk qonunchilikka ko‘ra nasiyaga sotilmaydi.",
            sort_order=7,
        )

        brands = {
            name: Brand.objects.create(name=name, slug=name.lower().replace(" ", "-"))
            for name in ("Apple", "Samsung", "Lenovo", "LG", "Artel", "Bosch", "IKEA Style", "Tashkent City")
        }

        # 8. Products
        def add_prod(store, wh, cat, brand_key, sku, title, slug, price, old_price, img, specs, stock_qty=18, status=ProductStatus.APPROVED, resell="LOW", rating=4.8, sales=32):
            p = Product.objects.create(
                store=store,
                category=cat,
                brand=brands[brand_key],
                sku=sku,
                title=title,
                slug=slug,
                description=f"{title} — rasmiy kafolat, tekshirilgan sifat va shaffof shartlar bilan.",
                specs=specs,
                cash_price=price,
                old_price=old_price,
                warranty_months=12,
                return_days=14,
                delivery_sla_days=1 if store == store1 else 2,
                installment_eligible=cat.installment_allowed,
                resell_risk_level=resell,
                status=status,
                rating=rating,
                review_count=4 if status == ProductStatus.APPROVED else 0,
                sales_count=sales,
            )
            ProductImage.objects.create(product=p, image_url=img, alt_text=title, is_primary=True)
            StockLevel.objects.create(product=p, warehouse=wh, quantity=stock_qty, min_threshold=4)
            return p

        p_iphone = add_prod(store1, wh1, c_phone, "Apple", "APL-16P-256", "Apple iPhone 16 Pro 256GB Titan", "iphone-16-pro-256", 14_990_000, 16_200_000, "/static/img/products/iphone-16-pro.jpg", {"Xotira": "256 GB", "Ekran": "6.3\" LTPO OLED", "Kamera": "48 MP Pro"}, stock_qty=12, resell="HIGH", rating=4.9, sales=88)
        p_s25 = add_prod(store1, wh1, c_phone, "Samsung", "SAM-S25-256", "Samsung Galaxy S25 Ultra 256GB", "samsung-s25-ultra", 13_800_000, 14_500_000, "/static/img/products/galaxy-s25-ultra.jpg", {"Xotira": "256 GB", "Ekran": "6.8\" AMOLED 2X", "Stilus": "S-Pen"}, stock_qty=15, resell="HIGH", rating=4.9, sales=74)
        add_prod(store1, wh1, c_phone, "Samsung", "SAM-A55-128", "Samsung Galaxy A55 5G 128GB", "samsung-a55-5g", 4_490_000, 4_950_000, "/static/img/products/galaxy-a55.jpg", {"Xotira": "128 GB", "RAM": "8 GB", "Batareya": "5000 mAh"}, stock_qty=28, resell="MEDIUM", rating=4.8, sales=126)
        p_mac = add_prod(store1, wh1, c_laptop, "Apple", "APL-MBA-M3", "MacBook Air 13 M3 16GB/512GB", "macbook-air-m3-16-512", 16_400_000, None, "/static/img/products/macbook-air-m3.jpg", {"Protsessor": "Apple M3", "RAM": "16 GB", "SSD": "512 GB"}, stock_qty=9, resell="HIGH", rating=5.0, sales=41)
        add_prod(store1, wh1, c_laptop, "Lenovo", "LNV-TP-14", "Lenovo ThinkPad E14 Gen 5 Core i5", "lenovo-thinkpad-e14", 8_600_000, 9_300_000, "/static/img/products/lenovo-thinkpad.jpg", {"Protsessor": "Intel Core i5-1335U", "RAM": "16 GB", "SSD": "512 GB"}, stock_qty=11, resell="MEDIUM", rating=4.7, sales=53)
        p_tv = add_prod(store2, wh2, c_tv, "LG", "LG-55-QLED", "LG QNED 55\" 4K Smart TV webOS", "lg-qned-55-4k", 8_950_000, 9_900_000, "/static/img/products/lg-qned-tv.jpg", {"Diagonal": "55 dyuym", "Ruxsat": "4K UHD", "Smart": "webOS 24"}, stock_qty=10, resell="LOW", rating=4.8, sales=64)
        add_prod(store2, wh2, c_tv, "Artel", "ART-43-FHD", "Artel 43\" Full HD Android TV", "artel-43-android-tv", 3_290_000, 3_650_000, "/static/img/products/lg-qned-tv.jpg", {"Diagonal": "43 dyuym", "OS": "Google Android TV", "Kafolat": "36 oy"}, stock_qty=22, resell="LOW", rating=4.6, sales=142)
        p_fridge = add_prod(store2, wh2, c_fridge, "Samsung", "SAM-RB38", "Samsung No Frost Inverter Sovutgich 385L", "samsung-no-frost-385", 7_850_000, 8_400_000, "/static/img/products/samsung-fridge.jpg", {"Hajm": "385 litr", "Tizim": "Total No Frost", "Sinf": "A++"}, stock_qty=7, resell="LOW", rating=4.9, sales=49)
        add_prod(store2, wh2, c_washer, "Bosch", "BSH-WGA-8", "Bosch Serie 4 Kir yuvish mashinasi 8 kg", "bosch-serie4-8kg", 6_900_000, None, "/static/img/products/bosch-washer.jpg", {"Sig‘im": "8 kg", "Aylanish": "1200 ayl/min", "Motor": "EcoSilence"}, stock_qty=2, resell="LOW", rating=4.9, sales=37)  # Low stock alert trigger!
        p_sofa = add_prod(store2, wh2, c_mebel, "IKEA Style", "MEB-LOFT-3", "Loft Komfort burchak divani (Velvet)", "loft-komfort-divan", 5_900_000, 6_700_000, "/static/img/products/loft-sofa.jpg", {"O‘lcham": "260 × 170 sm", "Mato": "Anti-dog‘ Velvet", "Karkas": "Qattiq yog‘och"}, stock_qty=6, resell="LOW", rating=4.7, sales=29)
        add_prod(store2, wh2, c_realty, "Tashkent City", "RE-OFIS-01", "Tijorat ofis maydoni 45 kv.m (Faqat naqd)", "tijorat-ofis-45kvm", 680_000_000, None, "/static/img/products/commercial-office.jpg", {"Maydon": "45 kv.m", "Qavat": "3-qavat", "Nasiya": "Qonunan taqiqlangan (27.1)"}, stock_qty=1, resell="LOW", rating=5.0, sales=2)
        # Pending Moderation & Draft items for Seller/Admin workflows
        add_prod(store1, wh1, c_laptop, "Lenovo", "LNV-LOQ-15", "Lenovo LOQ 15 RTX 4060 Gaming", "lenovo-loq-15-rtx4060", 12_900_000, None, "/static/img/products/lenovo-thinkpad.jpg", {"Protsessor": "Core i7", "GPU": "RTX 4060 8GB"}, stock_qty=5, status=ProductStatus.PENDING_REVIEW, sales=0)
        add_prod(store2, wh2, c_washer, "Artel", "ART-WM-7", "Artel 7kg Inverter Kir yuvish mashinasi", "artel-7kg-inverter", 4_100_000, None, "/static/img/products/bosch-washer.jpg", {"Sig‘im": "7 kg", "Inverter": "Ha"}, stock_qty=9, status=ProductStatus.PENDING_REVIEW, sales=0)

        # 9. Banners, Promos, Delivery Points
        Banner.objects.create(title="ZARVON Nasiya: 12 oygacha shaffof muddatli to‘lov", subtitle="Yashirin komissiyasiz, BHM×250 chegarasi ichida va istalgan vaqtda 0% jarimasiz muddatidan oldin yopish.", badge_text="2027 STANDARTI • SANDBOX", cta_label="Nasiya mahsulotlari", target_route="#catalog", theme_variant="navy", sort_order=1)
        Banner.objects.create(title="11.11 Katta Texnika Aksiyasi — 15% gacha chegirma", subtitle="Sovutgich, kir yuvish va QLED televizorlar birinchi qo‘ldan tez yetkazish bilan.", badge_text="KAMPANIYA • HIT", cta_label="Chegirmalarni ko‘rish", target_route="#catalog?sort=popular", theme_variant="gold", sort_order=2)
        Banner.objects.create(title="1 kunda yetkazib berish • Click, Payme va Uzum Bank", subtitle="Toshkent va hududiy PVR punktlariga bepul yetkazish hamda KATM/MIB orqali tezkor skoring.", badge_text="TEZKOR YETKAZISH", cta_label="Smartfonlar katalogi", target_route="#catalog?category=smartfonlar", theme_variant="navy", sort_order=3)
        PromoCode.objects.create(code="ZARVON11", title="11.11 Aksiyasi 300 000 so‘m chegirma", discount_fixed=300_000, min_order_amount=3_000_000, max_budget_uzs=30_000_000, expires_at=timezone.now() + timedelta(days=45))
        PromoCode.objects.create(code="BARAKA5", title="5% chegirma (max 500 000 so‘m)", discount_pct=5.0, min_order_amount=2_000_000, max_budget_uzs=50_000_000, expires_at=timezone.now() + timedelta(days=60))

        dp1 = DeliveryPoint.objects.create(name="ZARVON Chilonzor Punkti", region="Toshkent", address="Chilonzor 5-mavze, Integro yonida", working_hours="09:00 – 21:00")
        DeliveryPoint.objects.create(name="ZARVON Yunusobod Punkti", region="Toshkent", address="Amir Temur shoh ko‘chasi 108", working_hours="09:00 – 21:00")
        DeliveryPoint.objects.create(name="ZARVON Samarqand Markaz", region="Samarqand", address="Mirzo Ulug‘bek ko‘chasi 72", working_hours="09:30 – 20:00")

        # 10. Sample Orders, Verified Review & Installment Contracts
        # Order 1: Delivered (allows Azizbek to leave verified review!)
        ord1 = Order.objects.create(
            order_number="ZRV-261101-1001A",
            customer=customer,
            payment_channel="ZARVON_NASIYA",
            payment_method_label="ZARVON Nasiya 6 oy (Sandbox)",
            delivery_type="PICKUP",
            delivery_point=dp1,
            delivery_address=dp1.address,
            subtotal_amount=4_490_000,
            total_amount=4_490_000,
            status=OrderStatus.DELIVERED,
            idempotency_key="seed-order-1",
        )
        so1 = SellerOrder.objects.create(
            master_order=ord1,
            store=store1,
            sub_order_number="ZRV-261101-1001A-S1",
            subtotal_amount=4_490_000,
            commission_amount=314_300,
            holdback_amount=0,
            net_seller_payout=4_175_700,
            payout_status="PAID",
            status=OrderStatus.DELIVERED,
            delivered_at=timezone.now() - timedelta(days=20),
        )
        OrderItem.objects.create(seller_order=so1, product=p_iphone, product_title_snapshot=p_iphone.title, sku_snapshot=p_iphone.sku, unit_price_snapshot=4_490_000, quantity=1, line_total=4_490_000)
        Shipment.objects.create(seller_order=so1, tracking_number="TRK-ZRV1001", shipped_at=timezone.now() - timedelta(days=22))
        Review.objects.create(product=p_iphone, user=customer, rating=5, comment="Kamera va batareya zo‘r, shartnoma shaffof, oyma-oy to‘lov jadvali aniq.", seller_reply="Xaridingiz uchun rahmat! Savollaringiz bo‘lsa doim tayyormiz.", is_verified_purchase=True)

        # Active Installment Contract for ord1 (with 1st installment paid!)
        c1 = InstallmentContract.objects.create(
            contract_number="NSY-261101-9001",
            order=ord1,
            customer=customer,
            plan=p6,
            provider_type="OWN_NASIYA",
            provider_name="ZARVON Nasiya Operator (Sandbox DEMO)",
            principal_amount=4_200_000,
            down_payment=290_000,
            markup_amount=462_000,
            commission_amount=63_000,
            total_payable=4_725_000,
            remaining_balance=3_937_500,
            months=6,
            status=ContractStatus.ACTIVE,
            signed_method="OTP",
            signed_at=timezone.now() - timedelta(days=20),
            bhm_snapshot_uzs=bhm.amount_uzs,
            summary_terms={"monthly_payment": 787_500, "annualized_extra_pct": 25.0, "early_repayment_fee": "0 so‘m"},
        )
        OwnInstallmentProvider().build_schedule(contract=c1, start_date=(timezone.now() - timedelta(days=20)).date())
        first_item = c1.schedule_items.first()
        first_item.amount_paid = first_item.amount_due
        first_item.status = "PAID"
        first_item.paid_at = timezone.now() - timedelta(days=1)
        first_item.save()
        # Yaqinlashayotgan to‘lov sanalari (2 kun va 5 kun qoldi — Due Monitor va mijoz ogohlantiruvi uchun)
        second_item = c1.schedule_items.filter(installment_no=2).first()
        if second_item:
            second_item.due_date = timezone.localdate() + timedelta(days=2)
            second_item.save(update_fields=["due_date"])
        third_item = c1.schedule_items.filter(installment_no=3).first()
        if third_item:
            third_item.due_date = timezone.localdate() + timedelta(days=5)
            third_item.save(update_fields=["due_date"])

        # Order 2: Shipped with active Delivery OTP (ready to test handover!)
        ord2 = Order.objects.create(
            order_number="ZRV-261112-2002B",
            customer=customer,
            payment_channel="DIRECT_PAY",
            payment_method_label="Payme (Sandbox)",
            delivery_type="COURIER",
            delivery_address="Toshkent sh., Chilonzor 5-mavze, 12-uy",
            subtotal_amount=5_900_000,
            total_amount=5_900_000,
            status=OrderStatus.SHIPPED,
            idempotency_key="seed-order-2",
        )
        so2 = SellerOrder.objects.create(
            master_order=ord2,
            store=store2,
            sub_order_number="ZRV-261112-2002B-S1",
            subtotal_amount=5_900_000,
            commission_amount=501_500,
            holdback_amount=590_000,
            net_seller_payout=4_808_500,
            payout_status="HELD",
            status=OrderStatus.SHIPPED,
        )
        so2.issue_delivery_otp()
        OrderItem.objects.create(seller_order=so2, product=p_sofa, product_title_snapshot=p_sofa.title, sku_snapshot=p_sofa.sku, unit_price_snapshot=5_900_000, quantity=1, line_total=5_900_000)
        Shipment.objects.create(seller_order=so2, courier_name="ZARVON Kuryer", tracking_number="TRK-ZRV2002", shipped_at=timezone.now() - timedelta(hours=5))

        # Order 3 + Overdue contract for Collections DPD console demonstration
        ord3 = Order.objects.create(
            order_number="ZRV-261001-3003C",
            customer=customer_new,
            payment_channel="ZARVON_NASIYA",
            payment_method_label="ZARVON Nasiya 12 oy (Sandbox)",
            delivery_type="COURIER",
            delivery_address="Toshkent sh., Yunusobod 4-mavze",
            subtotal_amount=3_290_000,
            total_amount=3_290_000,
            status=OrderStatus.DELIVERED,
            idempotency_key="seed-order-3",
        )
        so3 = SellerOrder.objects.create(master_order=ord3, store=store2, sub_order_number="ZRV-261001-3003C-S1", subtotal_amount=3_290_000, commission_amount=279_650, net_seller_payout=3_010_350, payout_status="PAID", status=OrderStatus.DELIVERED)
        OrderItem.objects.create(seller_order=so3, product=p_tv, product_title_snapshot=p_tv.title, sku_snapshot=p_tv.sku, unit_price_snapshot=3_290_000, quantity=1, line_total=3_290_000)
        c3 = InstallmentContract.objects.create(
            contract_number="NSY-261001-8088",
            order=ord3,
            customer=customer_new,
            plan=p12,
            provider_type="OWN_NASIYA",
            provider_name="ZARVON Nasiya Operator (Sandbox DEMO)",
            principal_amount=3_290_000,
            down_payment=0,
            markup_amount=921_200,
            commission_amount=65_800,
            total_payable=4_277_000,
            remaining_balance=4_277_000,
            months=12,
            status=ContractStatus.OVERDUE,
            signed_method="OTP",
            signed_at=timezone.now() - timedelta(days=45),
            bhm_snapshot_uzs=bhm.amount_uzs,
        )
        OwnInstallmentProvider().build_schedule(contract=c3, start_date=(timezone.now() - timedelta(days=12)).date())
        first_ov = c3.schedule_items.first()
        first_ov.status = "OVERDUE"
        first_ov.save()

        col_case = CollectionCase.objects.create(contract=c3, assigned_agent=coll_agent, dpd_days=12, overdue_amount_uzs=first_ov.amount_due, stage="MIDDLE")
        CollectionAction.objects.create(case=col_case, actor=coll_agent, channel="CALL_WORK_HOURS", note="10:30 da ish vaqtida qo‘ng‘iroq qilindi; mijoz ish haqi tushgach to‘lashini bildirdi.", respectful_conduct_confirmed=True)
        RestructuringCase.objects.create(contract=c3, requested_by=coll_agent, reason="Mijoz vaqtincha oilaviy sabab bilan jadvalni 12 oyga qayta taqsimlashni so‘radi.", proposed_new_months=12)

        # 11. Payments, Reconciliation, Fraud, Security, Support & Audit
        PaymentRecord.objects.create(payment_intent_id="PAY-SEED-1001", provider="Payme", user=customer, order=ord1, contract=c1, amount=787_500, status="SUCCEEDED", reconciliation_ref="REC-ZRV-1001")
        ReconciliationRecord.objects.create(reconciliation_date=timezone.now().date(), provider="Payme", zarvon_total_uzs=787_500, provider_total_uzs=787_500, difference_uzs=0, status="MATCHED", note="Kunlik solishtirish to‘liq mos keldi.")
        ReconciliationRecord.objects.create(reconciliation_date=timezone.now().date() - timedelta(days=1), provider="Click", zarvon_total_uzs=5_900_000, provider_total_uzs=5_850_000, difference_uzs=-50_000, status="DISCREPANCY", note="Komissiya tafovuti tekshirilmoqda.")

        sig = FraudSignal.objects.create(user=customer_new, signal_type="HIGH_RESELL_RISK", severity="MEDIUM", summary="Yangi Start akkaunt qimmat smartfon kategoriyasida bir nechta ariza urindi.", metadata={"category": "Smartfonlar"})
        FraudCase.objects.create(signal=sig, assigned_to=fraud_analyst, status="OPEN")

        SecurityEvent.objects.create(event_type="RATE_LIMIT_TRIGGERED", severity="LOW", ip_address="185.139.12.44", description="Katalog narxlar sahifasida avtomatik skraping urinishi cheklandi (31.1).")
        SupportTicket.objects.create(
            ticket_number="TKT-2611-001",
            user=customer,
            category="GENERAL",
            subject="Muddatidan oldin to‘lashda komissiya bormi?",
            messages=[
                {"sender": customer.full_name, "role": "CUSTOMER", "text": "Shartnomani muddatidan 3 oy oldin yopsam qo‘shimcha haq olinadimi?", "at": timezone.now().isoformat()},
                {"sender": "ZARVON Yordam", "role": "SUPPORT_AGENT", "text": "Yo‘q! Qonunchilik va ZARVON qoidalariga ko‘ra muddatidan oldin qisman yoki to‘liq to‘lashda 0% komissiya va jarima olinadi.", "at": timezone.now().isoformat()},
            ],
            status="RESOLVED",
        )
        NotificationEvent.objects.create(user=customer, channel="TELEGRAM", category="TRANSACTIONAL", status="delivered", title="To‘lov eslatmasi", body_masked="Shartnoma #NSY-261101-9001 bo‘yicha navbatdagi to‘lov sanasi yaqinlashmoqda.")
        AuditLog.record(actor=super_admin, action="PLATFORM_SEEDED", object_type="System", reason="ZARVON Sandbox/Demo muhiti ishga tushirildi")
        self._ensure_v2_samples()
        self.stdout.write(self.style.SUCCESS("ZARVON ma'lumotlar bazasi muvaffaqiyatli to'ldirildi!"))

    def _ensure_v2_samples(self):
        """Idempotently populate KATM/MIB reports, tokenized cards, Click/Payme traces & due-soon items."""
        from django.conf import settings
        from config.utils import encrypt_field
        from apps.finance.models import (
            ExternalScoringReport,
            InstallmentContract,
            PaymentCard,
            PaymentReminderLog,
            PspTransaction,
        )

        today = timezone.localdate()
        customer = User.objects.filter(phone="+998901110001").first()
        customer_new = User.objects.filter(phone="+998901110002").first()
        coll_agent = User.objects.filter(phone="+998909990005").first()
        if not customer:
            return

        if not customer.inn_hash:
            customer.set_identity_fields(pinfl="31405940010012", passport="AD1234567", inn="305112849")
            customer.save(update_fields=["pinfl_hash", "pinfl_encrypted", "passport_encrypted", "inn_hash", "inn_encrypted"])

        c1 = InstallmentContract.objects.filter(contract_number="NSY-261101-9001").first()
        if c1:
            it2 = c1.schedule_items.filter(installment_no=2, status__in=["UPCOMING", "PARTIAL"]).first()
            if it2 and (it2.due_date - today).days > 4:
                it2.due_date = today + timedelta(days=2)
                it2.save(update_fields=["due_date"])
            it3 = c1.schedule_items.filter(installment_no=3, status__in=["UPCOMING", "PARTIAL"]).first()
            if it3 and (it3.due_date - today).days > 10:
                it3.due_date = today + timedelta(days=5)
                it3.save(update_fields=["due_date"])

        from apps.finance.scoring import run_katm_and_mib_scoring
        if not ExternalScoringReport.objects.filter(user=customer).exists():
            run_katm_and_mib_scoring(
                user=customer,
                pinfl="31405940010012",
                inn="305112849",
                birth_year=1994,
                monthly_income_uzs=9_500_000,
                requested_purchase_uzs=4_200_000,
                requested_months=12,
                scenario="moderate_credit",
            )

        if customer_new and not ExternalScoringReport.objects.filter(user=customer_new).exists():
            run_katm_and_mib_scoring(
                user=customer_new,
                pinfl="41205960010077",
                inn="",
                birth_year=1996,
                monthly_income_uzs=4_500_000,
                requested_purchase_uzs=3_290_000,
                requested_months=12,
                scenario="high_debt",
            )

        if not PaymentCard.objects.filter(user=customer).exists():
            PaymentCard.objects.create(
                user=customer,
                provider="Uzcard/Humo",
                card_brand="Uzcard",
                card_token_encrypted=encrypt_field("tok_seed_uzcard_8600_7742"),
                card_masked_pan="8600 **** **** 7742",
                expiry_masked="**/28",
                card_holder=customer.full_name,
                is_verified=True,
                is_default=True,
                auto_debit_enabled=True,
                is_demo=settings.ZARVON_SANDBOX_MODE,
            )
            PaymentCard.objects.create(
                user=customer,
                provider="Click",
                card_brand="Humo",
                card_token_encrypted=encrypt_field("tok_seed_humo_9860_3319"),
                card_masked_pan="9860 **** **** 3319",
                expiry_masked="**/29",
                card_holder=customer.full_name,
                is_verified=True,
                is_default=False,
                auto_debit_enabled=True,
                is_demo=settings.ZARVON_SANDBOX_MODE,
            )

        if not PspTransaction.objects.exists():
            from apps.commerce.models import Order
            ord1 = Order.objects.filter(order_number="ZRV-261101-1001A").first()
            ord2 = Order.objects.filter(order_number="ZRV-261112-2002B").first()
            PspTransaction.objects.create(
                psp_provider="Payme",
                external_trans_id="pm_seed_787500",
                merchant_trans_id="NSY-261101-9001",
                action_stage="PERFORMED",
                amount_tiyin=78_750_000,
                state_code=2,
                signature_verified=True,
                idempotency_key="seed-payme-c1-1",
                order=ord1,
                contract=c1,
                raw_payload_sanitized={"method": "PerformTransaction", "sandbox": True},
                is_demo=True,
            )
            if ord2:
                PspTransaction.objects.create(
                    psp_provider="Click",
                    external_trans_id="9041288101",
                    merchant_trans_id=ord2.order_number,
                    merchant_prepare_id="PREP-SEED2002",
                    action_stage="PERFORMED",
                    amount_tiyin=int(ord2.total_amount) * 100,
                    state_code=2,
                    signature_verified=True,
                    idempotency_key="seed-click-ord2",
                    order=ord2,
                    raw_payload_sanitized={"action": "1", "sandbox": True},
                    is_demo=True,
                )

        if c1 and not PaymentReminderLog.objects.filter(contract=c1).exists():
            due_it = c1.schedule_items.filter(installment_no=2).first()
            if due_it:
                PaymentReminderLog.objects.create(
                    contract=c1,
                    schedule_item=due_it,
                    user=customer,
                    window_tag="DUE_3_DAYS",
                    channel="SMS",
                    amount_due_uzs=due_it.amount_due,
                    due_date=due_it.due_date,
                    sent_by=coll_agent,
                    status="SENT",
                )

        studio_map = {
            "APL-16P-256": "/static/img/products/iphone-16-pro.jpg",
            "SAM-S25-256": "/static/img/products/galaxy-s25-ultra.jpg",
            "SAM-A55-128": "/static/img/products/galaxy-a55.jpg",
            "APL-MBA-M3": "/static/img/products/macbook-air-m3.jpg",
            "LNV-TP-14": "/static/img/products/lenovo-thinkpad.jpg",
            "LG-55-QLED": "/static/img/products/lg-qned-tv.jpg",
            "ART-43-FHD": "/static/img/products/lg-qned-tv.jpg",
            "SAM-RB38": "/static/img/products/samsung-fridge.jpg",
            "BSH-WGA-8": "/static/img/products/bosch-washer.jpg",
            "MEB-LOFT-3": "/static/img/products/loft-sofa.jpg",
            "RE-OFIS-01": "/static/img/products/commercial-office.jpg",
            "LNV-LOQ-15": "/static/img/products/lenovo-thinkpad.jpg",
            "ART-WM-7": "/static/img/products/bosch-washer.jpg",
        }
        for sku_code, img_path in studio_map.items():
            ProductImage.objects.filter(
                product__sku=sku_code,
                image_url__startswith="/static/icons/",
            ).update(image_url=img_path)

        first_banner = Banner.objects.order_by("sort_order").first()
        if first_banner:
            first_banner.title = "Kerakli mahsulot — qulay to‘lov bilan"
            first_banner.subtitle = "Bir nechta bank taklifini solishtiring va o‘zingizga mos to‘lovni tanlang."
            first_banner.cta_label = "Mahsulotlarni ko‘rish"
            first_banner.save(update_fields=["title", "subtitle", "cta_label"])

        if Banner.objects.count() < 3:
            Banner.objects.get_or_create(
                title="1 kunda yetkazib berish • Click, Payme va Uzum Bank",
                defaults={
                    "subtitle": "Toshkent va hududiy PVR punktlariga bepul yetkazish hamda KATM/MIB orqali tezkor skoring.",
                    "badge_text": "TEZKOR YETKAZISH",
                    "cta_label": "Smartfonlar katalogi",
                    "target_route": "#catalog?category=smartfonlar",
                    "theme_variant": "navy",
                    "sort_order": 3,
                },
            )

        bts_points = [
            ("BTS Express — Furqat / Navbahor", "Farg‘ona viloyati", "Furqat tumani, Navbahor shaharchasi, 1012-uy", "09:00 – 19:00"),
            ("BTS Express — Toshkent Chilonzor", "Toshkent", "Chilonzor tumani, Qatortol ko‘chasi 28", "09:00 – 20:00"),
            ("BTS Express — Andijon Markaz", "Andijon", "Bobur shoh ko‘chasi 45", "09:00 – 19:00"),
            ("BTS Express — Farg‘ona Markaz", "Farg‘ona", "Mustaqillik ko‘chasi 18", "09:00 – 19:00"),
            ("BTS Express — Namangan Markaz", "Namangan", "Alisher Navoiy ko‘chasi 64", "09:00 – 19:00"),
            ("BTS Express — Buxoro Markaz", "Buxoro", "Bahouddin Naqshband ko‘chasi 112", "09:00 – 19:00"),
            ("BTS Express — Qarshi (Qashqadaryo)", "Qashqadaryo", "O‘zbekiston ko‘chasi 221", "09:00 – 19:00"),
            ("BTS Express — Urganch (Xorazm)", "Xorazm", "Pahlavon Mahmud ko‘chasi 15", "09:00 – 19:00"),
            ("BTS Express — Nukus (Qoraqalpog‘iston)", "Nukus", "Do‘stlik guzari 56", "09:00 – 19:00"),
            ("BTS Express — Navoiy Markaz", "Navoiy", "G‘alaba shoh ko‘chasi 88", "09:00 – 19:00"),
            ("BTS Express — Jizzax & Termiz", "Jizzax", "Sharof Rashidov shoh ko‘chasi 14", "09:00 – 19:00"),
        ]
        for dp_name, dp_reg, dp_addr, dp_hrs in bts_points:
            DeliveryPoint.objects.get_or_create(
                name=dp_name,
                region=dp_reg,
                address=dp_addr,
                defaults={"working_hours": dp_hrs, "is_active": True},
            )
