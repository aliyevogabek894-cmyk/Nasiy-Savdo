"""Marketplace Catalog, Smart Uzbek Search, Reviews (Verified Buyers Only), Wishlists, CMS & Promos."""
from django.db.models import Avg
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.permissions import HasRolePermission
from config.utils import compute_monthly_installment, fuzzy_search_score
from apps.catalog.models import Banner, Brand, Category, Product, ProductStatus, PromoCode, Review, Wishlist
from apps.commerce.models import OrderItem, OrderStatus
from apps.finance.models import InstallmentPlan
from apps.governance.models import AuditLog, BhmValue, ComplianceRuleVersion


def _product_card_dict(p: Product, default_plan=None, bhm_limit: int = 110_000_000) -> dict:
    stock_avail = p.stock.available if hasattr(p, "stock") else 0
    installment_ok = bool(p.installment_eligible and p.category.installment_allowed and p.cash_price <= bhm_limit)
    indicative = None
    if installment_ok and default_plan:
        calc = compute_monthly_installment(p.cash_price, default_plan.months, default_plan.annual_markup_pct, default_plan.commission_pct)
        indicative = {
            "months": default_plan.months,
            "monthly_payment": calc["monthly_payment"],
            "total_payable": calc["total_payable"],
            "annualized_extra_pct": calc["annualized_extra_pct"],
            "label": "indikativ hisob",
        }
    imgs = [img.image_url for img in p.images.all()]
    discount_pct = 0
    if p.old_price and p.old_price > p.cash_price:
        discount_pct = round(((p.old_price - p.cash_price) / p.old_price) * 100)
    return {
        "id": str(p.id),
        "sku": p.sku,
        "title": p.title,
        "slug": p.slug,
        "store_id": str(p.store_id),
        "store_name": p.store.public_name,
        "store_rating": p.store.rating,
        "category_id": str(p.category_id),
        "category_name": p.category.name,
        "category_slug": p.category.slug,
        "category_installment_allowed": p.category.installment_allowed,
        "brand_name": p.brand.name if p.brand else "",
        "cash_price": p.cash_price,
        "old_price": p.old_price,
        "discount_pct": discount_pct,
        "warranty_months": p.warranty_months,
        "return_days": p.return_days,
        "delivery_sla_days": p.delivery_sla_days,
        "installment_eligible": installment_ok,
        "resell_risk_level": p.resell_risk_level,
        "rating": p.rating,
        "review_count": p.review_count,
        "sales_count": p.sales_count,
        "stock_available": stock_avail,
        "primary_image": imgs[0] if imgs else "",
        "images": imgs,
        "specs": p.specs,
        "description": p.description,
        "indicative_installment": indicative,
    }


class HomeMarketplaceView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        bhm = BhmValue.get_current_amount()
        rule = ComplianceRuleVersion.get_active()
        bhm_limit = bhm * rule.max_bhm_multiplier
        default_plan = InstallmentPlan.objects.filter(is_active=True).order_by("-months").first()

        banners = [
            {
                "id": str(b.id),
                "title": b.title,
                "subtitle": b.subtitle,
                "badge_text": b.badge_text,
                "cta_label": b.cta_label,
                "target_route": b.target_route,
                "theme_variant": b.theme_variant,
            }
            for b in Banner.objects.filter(is_active=True)
        ]
        categories = [
            {
                "id": str(c.id),
                "name": c.name,
                "name_ru": c.name_ru or c.name,
                "name_en": c.name_en or c.name,
                "slug": c.slug,
                "icon_name": c.icon_name,
                "installment_allowed": c.installment_allowed,
                "prohibition_note": c.prohibition_note,
                "attribute_schema": c.attribute_schema,
            }
            for c in Category.objects.all()
        ]
        approved_qs = (
            Product.objects.filter(status=ProductStatus.APPROVED, store__status="Active")
            .select_related("store", "category", "brand", "stock")
            .prefetch_related("images")
        )
        all_approved = list(approved_qs[:30])
        serialized = [_product_card_dict(p, default_plan, bhm_limit) for p in all_approved]

        installment_picks = [p for p in serialized if p["installment_eligible"]][:8]
        discounts = [p for p in serialized if p["discount_pct"] > 0][:8]
        newest = sorted(serialized, key=lambda x: x["sales_count"], reverse=True)[:8]

        return Response(
            {
                "banners": banners,
                "categories": categories,
                "brands": [{"id": str(b.id), "name": b.name, "slug": b.slug} for b in Brand.objects.all()],
                "installment_picks": installment_picks,
                "discounts": discounts,
                "new_arrivals": newest,
                "popular_queries": ["iPhone 16", "Samsung televizor", "Noutbuk", "Kir yuvish", "Mebel", "Sovutgich"],
                "compliance": {
                    "bhm_amount_uzs": bhm,
                    "max_months": rule.max_months,
                    "max_bhm_limit": bhm_limit,
                    "max_annual_extra_pct": rule.max_annual_extra_pct,
                },
            }
        )


class CatalogProductListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        bhm_limit = BhmValue.get_current_amount() * ComplianceRuleVersion.get_active().max_bhm_multiplier
        months_param = int(request.query_params.get("months") or 12)
        plan = InstallmentPlan.objects.filter(is_active=True, months=months_param).first() or InstallmentPlan.objects.filter(is_active=True).order_by("-months").first()

        qs = (
            Product.objects.filter(status=ProductStatus.APPROVED, store__status="Active")
            .select_related("store", "category", "brand", "stock")
            .prefetch_related("images")
        )
        cat_slug = (request.query_params.get("category") or "").strip()
        if cat_slug:
            qs = qs.filter(category__slug=cat_slug)
        brand_slug = (request.query_params.get("brand") or "").strip()
        if brand_slug:
            qs = qs.filter(brand__slug=brand_slug)
        if request.query_params.get("installment_only") == "true":
            qs = qs.filter(installment_eligible=True, category__installment_allowed=True, cash_price__lte=bhm_limit)
        min_price = request.query_params.get("min_price")
        if min_price and min_price.isdigit():
            qs = qs.filter(cash_price__gte=int(min_price))
        max_price = request.query_params.get("max_price")
        if max_price and max_price.isdigit():
            qs = qs.filter(cash_price__lte=int(max_price))
        delivery_max = request.query_params.get("delivery_days")
        if delivery_max and delivery_max.isdigit():
            qs = qs.filter(delivery_sla_days__lte=int(delivery_max))

        items = list(qs)
        q = (request.query_params.get("q") or "").strip()
        if q:
            scored = []
            for p in items:
                score = fuzzy_search_score(q, f"{p.title} {p.category.name} {p.brand.name if p.brand else ''} {p.search_index}")
                if score > 0:
                    scored.append((score, p))
            scored.sort(key=lambda x: x[0], reverse=True)
            items = [p for _, p in scored]

        results = [_product_card_dict(p, plan, bhm_limit) for p in items]

        max_monthly = request.query_params.get("max_monthly")
        if max_monthly and max_monthly.isdigit():
            limit_m = int(max_monthly)
            results = [r for r in results if r["indicative_installment"] and r["indicative_installment"]["monthly_payment"] <= limit_m]

        sort_by = request.query_params.get("sort") or "popular"
        if sort_by == "price_asc":
            results.sort(key=lambda x: x["cash_price"])
        elif sort_by == "price_desc":
            results.sort(key=lambda x: x["cash_price"], reverse=True)
        elif sort_by == "monthly_asc":
            results.sort(key=lambda x: x["indicative_installment"]["monthly_payment"] if x["indicative_installment"] else 10**12)
        elif not q:
            results.sort(key=lambda x: x["sales_count"], reverse=True)

        return Response({"count": len(results), "results": results})


class ProductDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        bhm_limit = BhmValue.get_current_amount() * ComplianceRuleVersion.get_active().max_bhm_multiplier
        p = (
            Product.objects.filter(slug=slug, status=ProductStatus.APPROVED)
            .select_related("store", "category", "brand", "stock")
            .prefetch_related("images", "reviews__user")
            .first()
        )
        if not p:
            return Response({"detail": "Mahsulot topilmadi yoki hali moderatsiyadan o‘tmagan."}, status=status.HTTP_404_NOT_FOUND)

        plans = InstallmentPlan.objects.filter(is_active=True).order_by("months")
        default_plan = plans.last()
        data = _product_card_dict(p, default_plan, bhm_limit)

        installment_quotes = []
        if data["installment_eligible"]:
            for pl in plans:
                calc = compute_monthly_installment(p.cash_price, pl.months, pl.annual_markup_pct, pl.commission_pct)
                installment_quotes.append(
                    {
                        "plan_id": str(pl.id),
                        "plan_name": pl.name,
                        "months": pl.months,
                        "annual_markup_pct": pl.annual_markup_pct,
                        "commission_pct": pl.commission_pct,
                        **calc,
                    }
                )
        data["installment_quotes"] = installment_quotes
        data["reviews"] = [
            {
                "id": str(r.id),
                "author": r.user.full_name,
                "rating": r.rating,
                "comment": r.comment,
                "seller_reply": r.seller_reply,
                "is_verified_purchase": r.is_verified_purchase,
                "created_at": r.created_at,
            }
            for r in p.reviews.filter(is_approved=True)
        ]
        similar = (
            Product.objects.filter(category=p.category, status=ProductStatus.APPROVED)
            .exclude(id=p.id)
            .select_related("store", "category", "brand", "stock")
            .prefetch_related("images")[:4]
        )
        data["similar_products"] = [_product_card_dict(s, default_plan, bhm_limit) for s in similar]
        return Response(data)


class ProductReviewCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        product = Product.objects.filter(id=pk, status=ProductStatus.APPROVED).first()
        if not product:
            return Response({"detail": "Mahsulot topilmadi."}, status=status.HTTP_404_NOT_FOUND)

        # Strict 29.2 & 31.1 check: ONLY verified purchasers can post reviews
        purchased = OrderItem.objects.filter(
            product=product,
            seller_order__master_order__customer=request.user,
            seller_order__status=OrderStatus.DELIVERED,
        ).exists()
        if not purchased:
            return Response(
                {"detail": "Faqat ushbu mahsulotni xarid qilib, qabul qilgan mijozlar sharh qoldira oladi (29.2)."},
                status=status.HTTP_403_FORBIDDEN,
            )

        rating = int(request.data.get("rating") or 5)
        comment = (request.data.get("comment") or "").strip()
        if rating < 1 or rating > 5 or not comment:
            return Response({"detail": "1–5 baho va sharh matni majburiy."}, status=status.HTTP_400_BAD_REQUEST)

        rev, _ = Review.objects.update_or_create(
            product=product,
            user=request.user,
            defaults={"rating": rating, "comment": comment, "is_verified_purchase": True, "is_approved": True},
        )
        agg = product.reviews.filter(is_approved=True).aggregate(avg=Avg("rating"))
        product.rating = round(agg["avg"] or rating, 1)
        product.review_count = product.reviews.filter(is_approved=True).count()
        product.save(update_fields=["rating", "review_count"])
        return Response({"ok": True, "review_id": str(rev.id)}, status=status.HTTP_201_CREATED)


class WishlistView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bhm_limit = BhmValue.get_current_amount() * ComplianceRuleVersion.get_active().max_bhm_multiplier
        plan = InstallmentPlan.objects.filter(is_active=True).order_by("-months").first()
        items = Wishlist.objects.filter(user=request.user).select_related("product__store", "product__category", "product__brand", "product__stock").prefetch_related("product__images")
        return Response(
            {
                "results": [
                    {
                        "wishlist_id": str(w.id),
                        "notify_on_price_drop": w.notify_on_price_drop,
                        "product": _product_card_dict(w.product, plan, bhm_limit),
                    }
                    for w in items
                ]
            }
        )

    def post(self, request):
        pid = request.data.get("product_id")
        product = Product.objects.filter(id=pid, status=ProductStatus.APPROVED).first()
        if not product:
            return Response({"detail": "Mahsulot topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        existing = Wishlist.objects.filter(user=request.user, product=product).first()
        if existing:
            existing.delete()
            return Response({"wishlisted": False})
        Wishlist.objects.create(user=request.user, product=product, notify_on_price_drop=True)
        return Response({"wishlisted": True}, status=status.HTTP_201_CREATED)


class ValidatePromoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        code = (request.data.get("code") or "").strip().upper()
        subtotal = int(request.data.get("subtotal") or 0)
        promo = PromoCode.objects.filter(code=code, is_active=True, expires_at__gte=timezone.now()).first()
        if not promo:
            return Response({"detail": "Promo-kod topilmadi yoki muddati tugagan."}, status=status.HTTP_404_NOT_FOUND)
        if subtotal < promo.min_order_amount:
            return Response({"detail": f"Minimal buyurtma summasi: {promo.min_order_amount:,} so‘m."}, status=status.HTTP_400_BAD_REQUEST)
        discount = promo.discount_fixed if promo.discount_fixed > 0 else round(subtotal * promo.discount_pct / 100.0)
        remaining_budget = max(0, promo.max_budget_uzs - promo.used_budget_uzs)
        discount = min(discount, remaining_budget)
        return Response({"ok": True, "code": promo.code, "title": promo.title, "discount_amount": discount})


class CategoryManagementView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(
            {
                "results": [
                    {
                        "id": str(c.id),
                        "name": c.name,
                        "slug": c.slug,
                        "icon_name": c.icon_name,
                        "installment_allowed": c.installment_allowed,
                        "prohibition_note": c.prohibition_note,
                        "attribute_schema": c.attribute_schema,
                    }
                    for c in Category.objects.all()
                ]
            }
        )

    def post(self, request):
        if not request.user.is_authenticated or request.user.role not in {"SUPER_ADMIN", "MARKETPLACE_ADMIN"}:
            return Response({"detail": "Faqat Marketplace Admin kategoriya boshqara oladi."}, status=status.HTTP_403_FORBIDDEN)
        name = (request.data.get("name") or "").strip()
        slug = (request.data.get("slug") or "").strip()
        installment_allowed = bool(request.data.get("installment_allowed", True))
        if not name or not slug:
            return Response({"detail": "Nom va slug majburiy."}, status=status.HTTP_400_BAD_REQUEST)
        cat = Category.objects.create(
            name=name,
            slug=slug,
            installment_allowed=installment_allowed,
            prohibition_note=request.data.get("prohibition_note", ""),
            attribute_schema=request.data.get("attribute_schema", []),
        )
        AuditLog.record(actor=request.user, action="CATEGORY_CREATED", object_type="Category", object_id=cat.id, reason="Kategoriya qo‘shildi")
        return Response({"ok": True, "id": str(cat.id)}, status=status.HTTP_201_CREATED)


class CmsBannerPromoView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "CONTENT_MANAGER", "MARKETPLACE_ADMIN", "AUDITOR"}

    def get(self, request):
        return Response(
            {
                "banners": [
                    {
                        "id": str(b.id),
                        "title": b.title,
                        "subtitle": b.subtitle,
                        "badge_text": b.badge_text,
                        "cta_label": b.cta_label,
                        "theme_variant": b.theme_variant,
                        "is_active": b.is_active,
                        "version": b.version,
                    }
                    for b in Banner.objects.all()
                ],
                "promos": [
                    {
                        "id": str(p.id),
                        "code": p.code,
                        "title": p.title,
                        "discount_pct": p.discount_pct,
                        "discount_fixed": p.discount_fixed,
                        "max_budget_uzs": p.max_budget_uzs,
                        "used_budget_uzs": p.used_budget_uzs,
                        "is_active": p.is_active,
                        "expires_at": p.expires_at,
                    }
                    for p in PromoCode.objects.all()
                ],
            }
        )

    def post(self, request):
        kind = request.data.get("kind")
        if kind == "banner":
            b = Banner.objects.create(
                title=request.data.get("title", "Yangi aksiya"),
                subtitle=request.data.get("subtitle", ""),
                badge_text=request.data.get("badge_text", "AKSIYA"),
                cta_label=request.data.get("cta_label", "Ko‘rish"),
                target_route=request.data.get("target_route", "#catalog"),
                theme_variant=request.data.get("theme_variant", "navy"),
            )
            AuditLog.record(actor=request.user, action="CMS_BANNER_CREATED", object_type="Banner", object_id=b.id, reason="CMS banner qo‘shildi")
            return Response({"ok": True, "id": str(b.id)}, status=status.HTTP_201_CREATED)
        if kind == "promo":
            if request.user.role == "CONTENT_MANAGER":
                return Response({"detail": "Content Manager narx va promo byudjetini o‘zgartira olmaydi (33-bo‘lim)."}, status=status.HTTP_403_FORBIDDEN)
            p = PromoCode.objects.create(
                code=request.data["code"].strip().upper(),
                title=request.data["title"],
                discount_pct=float(request.data.get("discount_pct", 0)),
                discount_fixed=int(request.data.get("discount_fixed", 0)),
                max_budget_uzs=int(request.data.get("max_budget_uzs", 10_000_000)),
                expires_at=timezone.now() + timezone.timedelta(days=30),
            )
            AuditLog.record(actor=request.user, action="PROMO_CREATED", object_type="PromoCode", object_id=p.id, reason="Promo-kod yaratildi")
            return Response({"ok": True, "id": str(p.id)}, status=status.HTTP_201_CREATED)
        return Response({"detail": "Noto‘g‘ri tur."}, status=status.HTTP_400_BAD_REQUEST)
