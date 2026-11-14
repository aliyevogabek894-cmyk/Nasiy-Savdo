"""Root URL routing for ZARVON Marketplace, PWA Shell, and Versioned REST API (/api/v1/)."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.utils import timezone
from django.views.generic import TemplateView

from apps.accounts.views import (
    DemoRoleSwitchView,
    LoginView,
    LogoutView,
    MakerCheckerDecisionView,
    MeView,
    ProfileView,
    RequestOtpView,
    StaffManagementView,
    VerifyMfaView,
)
from apps.catalog.views import (
    CatalogProductListView,
    CategoryManagementView,
    CmsBannerPromoView,
    HomeMarketplaceView,
    ProductDetailView,
    ProductReviewCreateView,
    ValidatePromoView,
    WishlistView,
)
from apps.commerce.views import (
    CartView,
    CheckoutView,
    DeliveryPointListView,
    OrdersListView,
    ReturnDecisionView,
    ReturnRequestCreateView,
    SellerOrderStatusUpdateView,
)
from apps.finance.views import (
    AdminInstallmentPlansView,
    AdminScoringReportsView,
    BankPartnersAdminView,
    BankWebhookReceiverView,
    ClickMerchantWebhookView,
    ContractRepayView,
    CustomerConsentsView,
    CustomerFinanceCabinetView,
    KycAndScoringView,
    NasiyaCalculatorView,
    PaymeMerchantRpcView,
    PaymentCardsView,
    PspCheckoutAndSimulatorView,
    ReconciliationAdminView,
    SelectBankOfferView,
    UpcomingPaymentsMonitorView,
)
from apps.governance.views import (
    AuditLogListView,
    BhmProposeUpdateView,
    ComplianceSummaryView,
    MaskedReportExportView,
    NotificationsView,
    PrivacyRequestsView,
    SecurityEventListView,
)
from apps.imports.views import (
    ExternalIntegrationView,
    ExternalSyncTriggerView,
    ImportBatchConfirmView,
    ImportBatchListAndErrorView,
    ImportErrorReportDownloadView,
    ImportSampleTemplateView,
    ImportUploadPreviewView,
)
from apps.inventory.views import InventoryStockView
from apps.risk_collections.views import (
    AdminDashboardView,
    CollectionsConsoleView,
    FraudConsoleView,
    RiskAssessmentsView,
    SupportTicketsView,
)
from apps.sellers.views import (
    AdminModerationDecisionView,
    AdminModerationQueueView,
    AdminSellerApplicationsView,
    AdminSellerDecisionView,
    AdminSellerInvitationView,
    SellerOnboardingSubmitView,
    SellerProductDetailView,
    SellerProductsView,
    SellerStaffInviteView,
    SellerStoreCabinetView,
    SellerVerifyInviteView,
)


def health_check(_request):
    return JsonResponse({"status": "healthy", "service": "zarvon-monolith", "timestamp": timezone.now().isoformat()})


def openapi_schema(_request):
    return JsonResponse(
        {
            "openapi": "3.0.3",
            "info": {"title": "ZARVON Marketplace & Multi-Bank Nasiya API", "version": "3.0.0"},
            "servers": [{"url": "/api/v1"}],
            "paths": {
                "/health/": {"get": {"summary": "Platform health check"}},
                "/auth/me/": {"get": {"summary": "Current user, RBAC role & limits"}},
                "/auth/login/": {"post": {"summary": "Password or OTP login"}},
                "/catalog/home/": {"get": {"summary": "Home banners, categories, discounts & installment picks"}},
                "/catalog/products/": {"get": {"summary": "Smart search & multi-filter catalog (Approved only)"}},
                "/commerce/checkout/": {"post": {"summary": "Idempotent 3-step checkout with atomic reservations"}},
                "/finance/calculator/": {"post": {"summary": "Compliance-guarded Nasiya calculator (<=12m, <=250 BHM, <=50%/yr)"}},
                "/finance/contracts/{id}/repay/": {"post": {"summary": "Scheduled or 0%-fee early repayment"}},
                "/imports/upload/": {"post": {"summary": "XLSX/CSV bulk import with formula injection protection"}},
            },
        }
    )


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("manifest.webmanifest", TemplateView.as_view(template_name="manifest.webmanifest", content_type="application/manifest+json")),
    path("sw.js", TemplateView.as_view(template_name="sw.js", content_type="application/javascript")),

    # System & OpenAPI
    path("api/v1/health/", health_check),
    path("api/v1/schema/", openapi_schema),

    # Accounts, Auth, RBAC & Maker-Checker
    path("api/v1/auth/me/", MeView.as_view()),
    path("api/v1/auth/otp/request/", RequestOtpView.as_view()),
    path("api/v1/auth/login/", LoginView.as_view()),
    path("api/v1/auth/demo-switch/", DemoRoleSwitchView.as_view()),
    path("api/v1/auth/mfa-verify/", VerifyMfaView.as_view()),
    path("api/v1/auth/logout/", LogoutView.as_view()),
    path("api/v1/accounts/profile/", ProfileView.as_view()),
    path("api/v1/accounts/staff/", StaffManagementView.as_view()),
    path("api/v1/accounts/maker-checker/<uuid:pk>/decide/", MakerCheckerDecisionView.as_view()),

    # Governance, BHM, Audit, Security, Privacy
    path("api/v1/governance/compliance/", ComplianceSummaryView.as_view()),
    path("api/v1/governance/bhm-propose/", BhmProposeUpdateView.as_view()),
    path("api/v1/governance/audit-logs/", AuditLogListView.as_view()),
    path("api/v1/governance/security-events/", SecurityEventListView.as_view()),
    path("api/v1/governance/notifications/", NotificationsView.as_view()),
    path("api/v1/governance/privacy-requests/", PrivacyRequestsView.as_view()),
    path("api/v1/governance/export/", MaskedReportExportView.as_view()),

    # Catalog, Smart Search, Reviews, CMS & Promo
    path("api/v1/catalog/home/", HomeMarketplaceView.as_view()),
    path("api/v1/catalog/products/", CatalogProductListView.as_view()),
    path("api/v1/catalog/products/<slug:slug>/", ProductDetailView.as_view()),
    path("api/v1/catalog/products/<uuid:pk>/reviews/", ProductReviewCreateView.as_view()),
    path("api/v1/catalog/wishlists/", WishlistView.as_view()),
    path("api/v1/catalog/promo/validate/", ValidatePromoView.as_view()),
    path("api/v1/catalog/categories/", CategoryManagementView.as_view()),
    path("api/v1/catalog/cms/", CmsBannerPromoView.as_view()),

    # Sellers, Onboarding & Moderation
    path("api/v1/sellers/invitations/", AdminSellerInvitationView.as_view()),
    path("api/v1/sellers/onboarding/verify-invite/", SellerVerifyInviteView.as_view()),
    path("api/v1/sellers/onboarding/submit/", SellerOnboardingSubmitView.as_view()),
    path("api/v1/sellers/applications/", AdminSellerApplicationsView.as_view()),
    path("api/v1/sellers/applications/<uuid:pk>/decide/", AdminSellerDecisionView.as_view()),
    path("api/v1/sellers/my-store/", SellerStoreCabinetView.as_view()),
    path("api/v1/sellers/my-store/staff/", SellerStaffInviteView.as_view()),
    path("api/v1/sellers/my-products/", SellerProductsView.as_view()),
    path("api/v1/sellers/my-products/<uuid:pk>/", SellerProductDetailView.as_view()),
    path("api/v1/sellers/moderation-queue/", AdminModerationQueueView.as_view()),
    path("api/v1/sellers/moderation-queue/<uuid:pk>/decide/", AdminModerationDecisionView.as_view()),

    # Imports & Inventory
    path("api/v1/imports/sample-template/", ImportSampleTemplateView.as_view()),
    path("api/v1/imports/upload/", ImportUploadPreviewView.as_view()),
    path("api/v1/imports/<uuid:batch_id>/confirm/", ImportBatchConfirmView.as_view()),
    path("api/v1/imports/<uuid:batch_id>/error-report/", ImportErrorReportDownloadView.as_view()),
    path("api/v1/imports/batches/", ImportBatchListAndErrorView.as_view()),
    path("api/v1/imports/integrations/", ExternalIntegrationView.as_view()),
    path("api/v1/imports/integrations/<uuid:pk>/sync/", ExternalSyncTriggerView.as_view()),
    path("api/v1/inventory/stock/", InventoryStockView.as_view()),

    # Commerce, Cart, Checkout, Sub-Orders & Returns
    path("api/v1/commerce/delivery-points/", DeliveryPointListView.as_view()),
    path("api/v1/commerce/cart/", CartView.as_view()),
    path("api/v1/commerce/checkout/", CheckoutView.as_view()),
    path("api/v1/commerce/orders/", OrdersListView.as_view()),
    path("api/v1/commerce/seller-orders/<uuid:pk>/status/", SellerOrderStatusUpdateView.as_view()),
    path("api/v1/commerce/seller-orders/<uuid:pk>/return/", ReturnRequestCreateView.as_view()),
    path("api/v1/commerce/returns/<uuid:pk>/decide/", ReturnDecisionView.as_view()),

    # Finance, Nasiya, Multi-Bank & Reconciliation
    path("api/v1/finance/calculator/", NasiyaCalculatorView.as_view()),
    path("api/v1/finance/consents/", CustomerConsentsView.as_view()),
    path("api/v1/finance/kyc/verify/", KycAndScoringView.as_view()),
    path("api/v1/finance/cabinet/", CustomerFinanceCabinetView.as_view()),
    path("api/v1/finance/cards/", PaymentCardsView.as_view()),
    path("api/v1/finance/psp/click/", ClickMerchantWebhookView.as_view()),
    path("api/v1/finance/psp/payme/", PaymeMerchantRpcView.as_view()),
    path("api/v1/finance/psp/checkout/", PspCheckoutAndSimulatorView.as_view()),
    path("api/v1/finance/due-monitor/", UpcomingPaymentsMonitorView.as_view()),
    path("api/v1/finance/scoring-reports/", AdminScoringReportsView.as_view()),
    path("api/v1/finance/contracts/<uuid:pk>/repay/", ContractRepayView.as_view()),
    path("api/v1/finance/bank-offers/<uuid:offer_id>/select/", SelectBankOfferView.as_view()),
    path("api/v1/finance/plans/", AdminInstallmentPlansView.as_view()),
    path("api/v1/finance/bank-partners/", BankPartnersAdminView.as_view()),
    path("api/v1/finance/webhooks/bank/", BankWebhookReceiverView.as_view()),
    path("api/v1/finance/reconciliation/", ReconciliationAdminView.as_view()),

    # Risk, Fraud, Collections, Support & Executive Dashboard
    path("api/v1/risk/dashboard/", AdminDashboardView.as_view()),
    path("api/v1/risk/assessments/", RiskAssessmentsView.as_view()),
    path("api/v1/risk/fraud/", FraudConsoleView.as_view()),
    path("api/v1/risk/collections/", CollectionsConsoleView.as_view()),
    path("api/v1/risk/tickets/", SupportTicketsView.as_view()),
]
