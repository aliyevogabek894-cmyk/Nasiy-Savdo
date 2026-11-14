"""Seller Invitations, Onboarding Workflow, Tenant-Isolated Store & Product Moderation APIs."""
import uuid
from django.contrib.auth import login
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from config.permissions import IsSellerTenantMember

from config.permissions import HasRolePermission, IsSellerTenantMember
from config.utils import hash_token
from apps.accounts.models import User, UserRole
from apps.catalog.models import Brand, Category, Product, ProductImage, ProductModeration, ProductStatus, ProductVersion
from apps.governance.models import AuditLog
from apps.inventory.models import StockLevel, Warehouse
from apps.sellers.models import (
    SellerApplication,
    SellerDocument,
    SellerInvitation,
    SellerOnboardingStatus,
    SellerStaff,
    Store,
)


class AdminSellerInvitationView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN", "AUDITOR"}

    def get(self, request):
        invites = SellerInvitation.objects.all()[:50]
        return Response(
            {
                "results": [
                    {
                        "id": str(i.id),
                        "company_name": i.company_name,
                        "target_phone": i.target_phone,
                        "target_email": i.target_email,
                        "status": i.status,
                        "expires_at": i.expires_at,
                        "is_valid": i.is_valid,
                        "token_hash_prefix": i.token_hash[:12] + "...",
                        "created_at": i.created_at,
                    }
                    for i in invites
                ]
            }
        )

    def post(self, request):
        company = (request.data.get("company_name") or "").strip()
        phone = (request.data.get("target_phone") or "").strip()
        email = (request.data.get("target_email") or "").strip()
        hours = int(request.data.get("expires_hours") or 72)
        if not company or (not phone and not email):
            return Response({"detail": "Kompaniya nomi va telefon/email majburiy."}, status=status.HTTP_400_BAD_REQUEST)

        invite, raw_token = SellerInvitation.issue_invitation(
            company_name=company,
            target_phone=phone,
            target_email=email,
            expires_hours=hours,
            created_by=request.user,
        )
        AuditLog.record(actor=request.user, action="SELLER_INVITE_ISSUED", object_type="SellerInvitation", object_id=invite.id, reason=f"{company} uchun bir martalik taklifnoma")
        return Response(
            {
                "ok": True,
                "invitation_id": str(invite.id),
                "one_time_invite_token": raw_token,
                "invite_url": f"/?invite={raw_token}#seller-onboarding",
                "note": "Tokenning faqat SHA-256 xeshi bazada saqlandi; ochiq token faqat bir marta ko‘rsatiladi.",
            },
            status=status.HTTP_201_CREATED,
        )


class SellerVerifyInviteView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_token = (request.data.get("token") or "").strip()
        if not raw_token:
            return Response({"detail": "Taklif tokeni kiritilmagan."}, status=status.HTTP_400_BAD_REQUEST)
        inv = SellerInvitation.objects.filter(token_hash=hash_token(raw_token)).first()
        if not inv or not inv.is_valid:
            return Response({"detail": "Taklifnoma yaroqsiz, muddati tugagan yoki allaqachon ishlatilgan (4.1)."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "valid": True,
                "company_name": inv.company_name,
                "target_phone": inv.target_phone,
                "target_email": inv.target_email,
                "expires_at": inv.expires_at,
            }
        )


class SellerOnboardingSubmitView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        raw_token = (request.data.get("token") or "").strip()
        inv = SellerInvitation.objects.select_for_update().filter(token_hash=hash_token(raw_token)).first()
        if not inv or not inv.is_valid:
            return Response({"detail": "Yaroqli taklifnoma topilmadi."}, status=status.HTTP_400_BAD_REQUEST)

        legal_name = (request.data.get("legal_name") or "").strip()
        public_name = (request.data.get("public_name") or "").strip()
        phone = (request.data.get("official_phone") or inv.target_phone).strip()
        rep_name = (request.data.get("representative_name") or "").strip()
        if not legal_name or not public_name or not phone or not rep_name or not request.data.get("terms_accepted"):
            return Response({"detail": "Barcha majburiy yuridik maydonlar va rozilik to‘ldirilishi shart."}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(
            phone=phone,
            defaults={"full_name": rep_name, "email": request.data.get("official_email", ""), "role": UserRole.SELLER_OWNER, "is_phone_verified": True},
        )
        if created or request.data.get("password"):
            user.set_password(request.data.get("password") or "ZarvonSeller2026!")
            user.role = UserRole.SELLER_OWNER
            user.save()

        app = SellerApplication.objects.create(
            invitation=inv,
            applicant=user,
            legal_name=legal_name,
            public_name=public_name,
            entity_type=request.data.get("entity_type", "MChJ"),
            stir_number=request.data.get("stir_number", ""),
            representative_name=rep_name,
            official_phone=phone,
            official_email=request.data.get("official_email", inv.target_email),
            legal_address=request.data.get("legal_address", "Toshkent"),
            return_address=request.data.get("return_address", "Toshkent"),
            product_categories=request.data.get("product_categories", ["Smartfonlar"]),
            delivery_regions=request.data.get("delivery_regions", ["Toshkent", "Samarqand"]),
            terms_accepted_version="2026.3",
            terms_accepted_at=timezone.now(),
            status=SellerOnboardingStatus.SUBMITTED,
        )
        app.set_bank_details(request.data.get("bank_details", "20208000000000000001"))
        app.save()

        SellerDocument.objects.create(
            application=app,
            doc_type="Guvohnoma / Litsenziya",
            file_name=request.data.get("document_name", "guvohnoma.pdf"),
            private_path=f"private/sellers/{app.id}/guvohnoma.pdf",
            malware_scan_status="CLEAN",
        )
        inv.used_at = timezone.now()
        inv.status = SellerOnboardingStatus.SUBMITTED
        inv.save()

        login(request, user)
        AuditLog.record(actor=user, action="SELLER_APPLICATION_SUBMITTED", object_type="SellerApplication", object_id=app.id, reason="Taklifnoma orqali ariza yuborildi")
        return Response({"ok": True, "application_id": str(app.id), "status": app.status}, status=status.HTTP_201_CREATED)


class AdminSellerApplicationsView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN", "AUDITOR"}

    def get(self, request):
        apps = SellerApplication.objects.select_related("applicant").all()
        stores = Store.objects.select_related("owner").all()
        return Response(
            {
                "applications": [
                    {
                        "id": str(a.id),
                        "legal_name": a.legal_name,
                        "public_name": a.public_name,
                        "entity_type": a.entity_type,
                        "stir_number": a.stir_number,
                        "representative_name": a.representative_name,
                        "official_phone": a.official_phone,
                        "masked_bank": a.get_masked_bank_details(),
                        "status": a.status,
                        "reason_code": a.reason_code,
                        "reviewer_note": a.reviewer_note,
                        "created_at": a.created_at,
                    }
                    for a in apps
                ],
                "stores": [
                    {
                        "id": str(s.id),
                        "public_name": s.public_name,
                        "legal_name": s.legal_name,
                        "owner_name": s.owner.full_name,
                        "status": s.status,
                        "commission_pct": s.commission_pct,
                        "holdback_pct": s.holdback_pct,
                        "rating": s.rating,
                        "masked_bank": s.get_masked_bank(),
                    }
                    for s in stores
                ],
            }
        )


class AdminSellerDecisionView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN"}

    @transaction.atomic
    def post(self, request, pk):
        app = SellerApplication.objects.select_for_update().filter(id=pk).first()
        if not app:
            return Response({"detail": "Ariza topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        decision = request.data.get("status")
        reason_code = (request.data.get("reason_code") or "COMPLIANCE_OK").strip()
        note = (request.data.get("note") or "").strip()
        if decision not in SellerOnboardingStatus.values or (decision in {"Rejected", "Suspended", "Needs Info"} and not note):
            return Response({"detail": "Rad etish/to‘xtatish/qo‘shimcha ma’lumot uchun sabab kodi va izoh majburiy (3.2)."}, status=status.HTTP_400_BAD_REQUEST)

        old_status = app.status
        app.status = decision
        app.reason_code = reason_code
        app.reviewer_note = note
        app.reviewed_by = request.user
        app.save()

        store_id = None
        if decision == SellerOnboardingStatus.APPROVED and not hasattr(app, "store"):
            slug_base = slugify(app.public_name) or "store"
            slug = f"{slug_base}-{str(app.id)[:6]}"
            store = Store.objects.create(
                owner=app.applicant,
                application=app,
                legal_name=app.legal_name,
                public_name=app.public_name,
                slug=slug,
                logo_text=app.public_name[:2].upper(),
                official_phone=app.official_phone,
                official_email=app.official_email,
                legal_address=app.legal_address,
                return_address=app.return_address,
                delivery_regions=app.delivery_regions,
                bank_account_encrypted=app.bank_details_encrypted,
            )
            Warehouse.objects.create(store=store, name=f"{store.public_name} Asosiy ombor", address=app.legal_address)
            store_id = str(store.id)
        elif decision in {SellerOnboardingStatus.SUSPENDED, SellerOnboardingStatus.TERMINATED} and hasattr(app, "store"):
            app.store.status = "Suspended" if decision == SellerOnboardingStatus.SUSPENDED else "Terminated"
            app.store.suspension_reason = note
            app.store.save()

        AuditLog.record(
            actor=request.user,
            action=f"SELLER_{decision.upper().replace(' ', '_')}",
            object_type="SellerApplication",
            object_id=app.id,
            reason=f"[{reason_code}] {note}",
            before={"status": old_status},
            after={"status": decision, "store_id": store_id},
        )
        return Response({"ok": True, "status": decision, "store_id": store_id})


def _get_actor_store(user) -> Store | None:
    store_ids = user.get_accessible_store_ids()
    if not store_ids:
        return None
    return Store.objects.filter(id=store_ids[0]).first()


class SellerStoreCabinetView(APIView):
    permission_classes = [IsSellerTenantMember]

    def get(self, request):
        store = _get_actor_store(request.user)
        if not store:
            return Response({"detail": "Sizga biriktirilgan faol do‘kon topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, store)

        products = store.products.all()
        from apps.commerce.models import SellerOrder, ReturnRequest
        sub_orders = SellerOrder.objects.filter(store=store)
        returns = ReturnRequest.objects.filter(seller_order__store=store)
        low_stocks = StockLevel.objects.filter(product__store=store).select_related("product")
        low_list = [
            {"product_id": str(s.product_id), "title": s.product.title, "sku": s.product.sku, "available": s.available, "min_threshold": s.min_threshold}
            for s in low_stocks
            if s.is_low_stock
        ]
        total_sales = sum(o.subtotal_amount for o in sub_orders.exclude(status="Cancelled"))
        total_holdback = sum(o.holdback_amount for o in sub_orders.filter(payout_status="HELD"))
        total_net_payout = sum(o.net_seller_payout for o in sub_orders.exclude(status="Cancelled"))

        return Response(
            {
                "store": {
                    "id": str(store.id),
                    "public_name": store.public_name,
                    "legal_name": store.legal_name,
                    "description": store.description,
                    "official_phone": store.official_phone,
                    "legal_address": store.legal_address,
                    "return_address": store.return_address,
                    "working_hours": store.working_hours,
                    "return_policy": store.return_policy,
                    "delivery_regions": store.delivery_regions,
                    "commission_pct": store.commission_pct,
                    "holdback_pct": store.holdback_pct,
                    "settlement_days": store.settlement_days,
                    "masked_bank": store.get_masked_bank(),
                    "rating": store.rating,
                    "status": store.status,
                },
                "kpis": {
                    "total_products": products.count(),
                    "approved_products": products.filter(status=ProductStatus.APPROVED).count(),
                    "pending_moderation": products.filter(status=ProductStatus.PENDING_REVIEW).count(),
                    "rejected_products": products.filter(status=ProductStatus.REJECTED).count(),
                    "total_orders": sub_orders.count(),
                    "open_returns": returns.filter(status="PENDING").count(),
                    "total_sales_uzs": total_sales,
                    "total_holdback_uzs": total_holdback,
                    "net_payout_uzs": total_net_payout,
                },
                "low_stock_alerts": low_list,
                "staff": [
                    {
                        "id": str(st.id),
                        "full_name": st.user.full_name,
                        "phone": st.user.phone,
                        "position_title": st.position_title,
                        "allowed_sections": st.allowed_sections,
                        "is_active": st.is_active,
                    }
                    for st in store.staff_members.select_related("user").all()
                ],
                "is_owner": store.owner_id == request.user.id,
            }
        )

    def patch(self, request):
        store = _get_actor_store(request.user)
        if not store:
            return Response({"detail": "Do‘kon topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        if store.owner_id != request.user.id:
            return Response({"detail": "Do‘kon profilini faqat Seller Owner tahrirlay oladi (2-bo‘lim)."}, status=status.HTTP_403_FORBIDDEN)
        for field in ("public_name", "description", "working_hours", "return_policy", "official_phone"):
            if field in request.data:
                setattr(store, field, request.data[field])
        store.save()
        AuditLog.record(actor=request.user, action="STORE_PROFILE_UPDATED", object_type="Store", object_id=store.id, reason="Do‘kon profili yangilandi")
        return Response({"ok": True})


class SellerStaffInviteView(APIView):
    permission_classes = [IsSellerTenantMember]

    def post(self, request):
        store = _get_actor_store(request.user)
        if not store or store.owner_id != request.user.id:
            return Response({"detail": "Xodim qo‘shish faqat Seller Owner vakolatiga kiradi (2-bo‘lim)."}, status=status.HTTP_403_FORBIDDEN)
        phone = (request.data.get("phone") or "").strip()
        full_name = (request.data.get("full_name") or "").strip()
        position = (request.data.get("position_title") or "Katalog operatori").strip()
        sections = request.data.get("allowed_sections") or ["products", "orders"]
        if not phone or not full_name:
            return Response({"detail": "Telefon va ism majburiy."}, status=status.HTTP_400_BAD_REQUEST)
        staff_user, created = User.objects.get_or_create(
            phone=phone,
            defaults={"full_name": full_name, "role": UserRole.SELLER_STAFF, "is_phone_verified": True},
        )
        if created:
            staff_user.set_password("ZarvonStaff2026!")
            staff_user.save()
        SellerStaff.objects.update_or_create(
            store=store,
            user=staff_user,
            defaults={"position_title": position, "allowed_sections": sections, "is_active": True},
        )
        AuditLog.record(actor=request.user, action="SELLER_STAFF_ADDED", object_type="Store", object_id=store.id, reason=f"{full_name} ({sections})")
        return Response({"ok": True}, status=status.HTTP_201_CREATED)


class SellerProductsView(APIView):
    permission_classes = [IsSellerTenantMember]

    def get(self, request):
        store = _get_actor_store(request.user)
        if not store:
            return Response({"results": []})
        qs = store.products.select_related("category", "brand", "stock").prefetch_related("images")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(
            {
                "results": [
                    {
                        "id": str(p.id),
                        "sku": p.sku,
                        "title": p.title,
                        "slug": p.slug,
                        "category_id": str(p.category_id),
                        "category_name": p.category.name,
                        "brand_name": p.brand.name if p.brand else "",
                        "cash_price": p.cash_price,
                        "old_price": p.old_price,
                        "status": p.status,
                        "rejection_reason": p.rejection_reason,
                        "stock_quantity": p.stock.quantity if hasattr(p, "stock") else 0,
                        "stock_available": p.stock.available if hasattr(p, "stock") else 0,
                        "primary_image": p.images.first().image_url if p.images.exists() else "",
                        "sales_count": p.sales_count,
                        "updated_at": p.updated_at,
                    }
                    for p in qs
                ]
            }
        )

    @transaction.atomic
    def post(self, request):
        store = _get_actor_store(request.user)
        if not store:
            return Response({"detail": "Faol do‘kon topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        title = (request.data.get("title") or "").strip()
        sku = (request.data.get("sku") or "").strip()
        cash_price = int(request.data.get("cash_price") or 0)
        cat_id = request.data.get("category_id")
        submit_action = request.data.get("submit", True)

        if not title or not sku or cash_price <= 0 or not cat_id:
            return Response({"detail": "Nomi, noyob SKU, musbat naqd narx va kategoriya majburiy (5.1)."}, status=status.HTTP_400_BAD_REQUEST)
        if Product.objects.filter(store=store, sku=sku).exists():
            return Response({"detail": f"SKU '{sku}' sizning do‘koningizda allaqachon mavjud."}, status=status.HTTP_400_BAD_REQUEST)

        cat = Category.objects.filter(id=cat_id).first()
        if not cat:
            return Response({"detail": "Kategoriya topilmadi."}, status=status.HTTP_400_BAD_REQUEST)
        brand_name = (request.data.get("brand_name") or "").strip()
        brand = None
        if brand_name:
            brand, _ = Brand.objects.get_or_create(slug=slugify(brand_name), defaults={"name": brand_name})

        initial_status = ProductStatus.PENDING_REVIEW if submit_action else ProductStatus.DRAFT
        product = Product.objects.create(
            store=store,
            category=cat,
            brand=brand,
            sku=sku,
            title=title,
            slug=f"{slugify(title)[:80]}-{uuid.uuid4().hex[:6]}",
            description=request.data.get("description") or title,
            specs=request.data.get("specs") or {},
            cash_price=cash_price,
            old_price=int(request.data["old_price"]) if request.data.get("old_price") else None,
            warranty_months=int(request.data.get("warranty_months") or 12),
            return_days=int(request.data.get("return_days") or 14),
            installment_eligible=bool(request.data.get("installment_eligible", True)) and cat.installment_allowed,
            status=initial_status,
        )
        img_url = (request.data.get("image_url") or "").strip()
        if img_url:
            ProductImage.objects.create(product=product, image_url=img_url, alt_text=title, is_primary=True)

        wh = store.warehouses.first()
        StockLevel.objects.create(product=product, warehouse=wh, quantity=int(request.data.get("stock_quantity") or 10))
        AuditLog.record(actor=request.user, action="SELLER_PRODUCT_CREATED", object_type="Product", object_id=product.id, reason=f"Holat: {initial_status}")
        return Response({"ok": True, "id": str(product.id), "status": product.status}, status=status.HTTP_201_CREATED)


class SellerProductDetailView(APIView):
    permission_classes = [IsSellerTenantMember]

    @transaction.atomic
    def patch(self, request, pk):
        product = Product.objects.filter(id=pk).select_related("store", "stock").first()
        if not product:
            return Response({"detail": "Mahsulot topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, product)

        new_price = int(request.data.get("cash_price") or product.cash_price)
        if new_price <= 0:
            return Response({"detail": "Narx nol yoki manfiy bo‘lishi mumkin emas."}, status=status.HTTP_400_BAD_REQUEST)

        # Price change rule (5.2): sharp price swings (>=35%) or key info changes trigger re-moderation
        sharp_price_change = abs(new_price - product.cash_price) / max(1, product.cash_price) >= 0.35
        title_changed = bool(request.data.get("title") and request.data["title"] != product.title)

        if product.status == ProductStatus.APPROVED and (title_changed or sharp_price_change):
            ProductVersion.objects.create(
                product=product,
                version_number=product.versions.count() + 1,
                previous_snapshot={"title": product.title, "cash_price": product.cash_price},
                proposed_snapshot={"title": request.data.get("title", product.title), "cash_price": new_price},
                submitted_by=request.user,
                status=ProductStatus.PENDING_REVIEW,
            )
            product.status = ProductStatus.PENDING_REVIEW

        if "title" in request.data:
            product.title = request.data["title"]
        if "description" in request.data:
            product.description = request.data["description"]
        product.cash_price = new_price
        if "old_price" in request.data:
            product.old_price = int(request.data["old_price"]) if request.data["old_price"] else None
        if "image_url" in request.data and request.data["image_url"]:
            img_url = str(request.data["image_url"]).strip()[:500]
            if img_url.startswith("/") or img_url.startswith("https://") or img_url.startswith("http://"):
                from apps.catalog.models import ProductImage

                primary_img = product.images.filter(is_primary=True).first() or product.images.first()
                if primary_img:
                    primary_img.image_url = img_url
                    primary_img.save(update_fields=["image_url"])
                else:
                    ProductImage.objects.create(
                        product=product,
                        image_url=img_url,
                        alt_text=product.title[:180],
                        is_primary=True,
                        sort_order=0,
                    )
        if request.data.get("submit"):
            product.status = ProductStatus.PENDING_REVIEW
        product.save()

        if "stock_quantity" in request.data and hasattr(product, "stock"):
            product.stock.quantity = max(0, int(request.data["stock_quantity"]))
            product.stock.save(update_fields=["quantity", "updated_at"])

        return Response({"ok": True, "status": product.status})


class SellerProductImageUploadView(APIView):
    """Upload & sanitize a seller product photo (JPEG/PNG/WEBP -> clean Web-optimized JPEG)."""

    permission_classes = [IsSellerTenantMember]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 5 * 1024 * 1024

    def post(self, request):
        upload = request.FILES.get("image") or request.FILES.get("file")
        if not upload:
            return Response({"detail": "Rasm fayli yuborilmadi (image)."}, status=400)
        if upload.size > self.MAX_BYTES:
            return Response({"detail": "Rasm hajmi 5 MB dan oshmasligi kerak."}, status=400)

        try:
            img = Image.open(upload)
            img.verify()
            upload.seek(0)
            img = Image.open(upload)
            img = ImageOps.exif_transpose(img)
        except (UnidentifiedImageError, Exception):
            return Response(
                {"detail": "Noto‘g‘ri yoki shikastlangan rasm fayli. JPEG, PNG yoki WEBP yuklang."},
                status=400,
            )

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            clean_img = bg
        else:
            clean_img = img.convert("RGB")

        clean_img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

        dest_dir = Path(settings.MEDIA_ROOT) / "products"
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex[:16]}.jpg"
        dest_path = dest_dir / filename
        clean_img.save(dest_path, format="JPEG", quality=86, optimize=True)

        image_url = f"{settings.MEDIA_URL.rstrip('/')}/products/{filename}"

        product_id = request.data.get("product_id")
        if product_id:
            from apps.catalog.models import Product, ProductImage

            store_ids = set(request.user.get_accessible_store_ids())
            product = Product.objects.filter(pk=product_id).first()
            if not product or (
                request.user.role not in {"SUPER_ADMIN", "MARKETPLACE_ADMIN"} and product.store_id not in store_ids
            ):
                return Response({"detail": "Mahsulot topilmadi yoki ruxsat yo‘q."}, status=403)
            primary = product.images.filter(is_primary=True).first() or product.images.first()
            if primary:
                primary.image_url = image_url
                primary.save(update_fields=["image_url"])
            else:
                ProductImage.objects.create(
                    product=product,
                    image_url=image_url,
                    alt_text=product.title[:180],
                    is_primary=True,
                    sort_order=0,
                )

        return Response(
            {
                "ok": True,
                "image_url": image_url,
                "width": clean_img.width,
                "height": clean_img.height,
            },
            status=201,
        )


class AdminModerationQueueView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN", "AUDITOR"}

    def get(self, request):
        pending = Product.objects.filter(status__in=[ProductStatus.PENDING_REVIEW, ProductStatus.REJECTED]).select_related("store", "category", "brand").prefetch_related("versions", "images")
        logs = ProductModeration.objects.select_related("product", "moderator").all()[:25]
        return Response(
            {
                "queue": [
                    {
                        "id": str(p.id),
                        "sku": p.sku,
                        "title": p.title,
                        "store_name": p.store.public_name,
                        "category_name": p.category.name,
                        "cash_price": p.cash_price,
                        "status": p.status,
                        "rejection_reason": p.rejection_reason,
                        "primary_image": p.images.first().image_url if p.images.exists() else "",
                        "latest_version": (
                            {
                                "previous": p.versions.first().previous_snapshot,
                                "proposed": p.versions.first().proposed_snapshot,
                            }
                            if p.versions.exists()
                            else None
                        ),
                    }
                    for p in pending
                ],
                "history": [
                    {
                        "id": str(m.id),
                        "product_title": m.product.title,
                        "moderator": m.moderator.full_name if m.moderator else "Admin",
                        "decision": m.decision,
                        "reason_code": m.reason_code,
                        "comment": m.comment,
                        "created_at": m.created_at,
                    }
                    for m in logs
                ],
            }
        )


class AdminModerationDecisionView(APIView):
    permission_classes = [HasRolePermission]
    allowed_roles = {"SUPER_ADMIN", "MARKETPLACE_ADMIN"}

    @transaction.atomic
    def post(self, request, pk):
        product = Product.objects.filter(id=pk).first()
        if not product:
            return Response({"detail": "Mahsulot topilmadi."}, status=status.HTTP_404_NOT_FOUND)
        decision = request.data.get("decision")  # Approved / Rejected
        reason_code = (request.data.get("reason_code") or "QUALITY_CHECK").strip()
        comment = (request.data.get("comment") or "").strip()
        if decision not in {"Approved", "Rejected"}:
            return Response({"detail": "Qaror Approved yoki Rejected bo‘lishi kerak."}, status=status.HTTP_400_BAD_REQUEST)
        if decision == "Rejected" and not comment:
            return Response({"detail": "Rad etish uchun sabab kodi va izoh majburiy (5.2)."}, status=status.HTTP_400_BAD_REQUEST)

        old_status = product.status
        product.status = ProductStatus.APPROVED if decision == "Approved" else ProductStatus.REJECTED
        product.rejection_reason = "" if decision == "Approved" else f"[{reason_code}] {comment}"
        product.save()

        ProductModeration.objects.create(
            product=product,
            moderator=request.user,
            decision=decision,
            reason_code=reason_code,
            comment=comment,
            previous_value={"status": old_status},
            new_value={"status": product.status},
        )
        AuditLog.record(actor=request.user, action=f"PRODUCT_{decision.upper()}", object_type="Product", object_id=product.id, reason=f"[{reason_code}] {comment}")
        return Response({"ok": True, "status": product.status})
