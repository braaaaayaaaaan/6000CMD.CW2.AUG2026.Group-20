from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from user import account_views as accounts
from asset.media import asset_file

from user import views as user_views
from user import monitoring
from asset import views as asset_views
from asset.views import (
    asset_usage_count,
    clear_all_tags,
    get_new_version_no,
    get_all_file_versions,
    delete_asset_by_code,
)

router = routers.DefaultRouter()
router.register(r"users", user_views.UserViewSet)
router.register(r"groups", user_views.GroupViewSet)
router.register(r"assets", asset_views.AssetViewSet)
router.register(r"tags", asset_views.TagViewSet)
router.register(r"api/security/audit-events", monitoring.AuditEventViewSet, basename="security-audit")
router.register(r"api/security/alerts", monitoring.SecurityAlertViewSet, basename="security-alert")

urlpatterns = [
    path("api/security/overview/", monitoring.SecurityOverview.as_view(), name="security-overview"),
    path("api/token/", accounts.NewTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", accounts.NewTokenRefreshView.as_view(), name="token_refresh"),
    path("api/logout/", accounts.LogoutView.as_view(), name="logout"),
    path("api/logout-all/", accounts.LogoutAllView.as_view(), name="logout-all"),
    path("api/account/csrf/", accounts.CsrfView.as_view()),
    path("api/account/me/", accounts.MeView.as_view()),
    path("api/account/verify-email/", accounts.VerifyEmailView.as_view()),
    path("api/account/resend-verification/", accounts.VerificationResendView.as_view()),
    path("api/account/forgot-password/", accounts.ForgotPasswordView.as_view()),
    path("api/account/reset-password/", accounts.ResetPasswordView.as_view()),
    path("api/account/mfa/enrol/", accounts.MfaEnrolView.as_view()),
    path("api/account/mfa/confirm/", accounts.MfaConfirmView.as_view()),
    path("api/account/mfa/verify/", accounts.MfaVerifyView.as_view()),
    path("api/account/mfa/setup/", accounts.MfaSetupView.as_view()),
    path("api/account/mfa/remove/", accounts.MfaRemoveView.as_view()),
    path("api/account/mfa/replace/", accounts.MfaReplaceView.as_view()),
    path("media/assets/<uuid:asset_id>/", asset_file, name="asset-file"),
    path("admin/login/", accounts.admin_login),
    path("admin/", admin.site.urls),
    path("", include(router.urls)),
    path("api-auth/", include(([
        path("login/", accounts.admin_login, name="login"),
        path("logout/", accounts.BrowsableLogoutView.as_view(), name="logout"),
    ], "rest_framework"), namespace="rest_framework")),
    path("api-authlogin/", accounts.admin_login),
    path("api-authlogout/", accounts.BrowsableLogoutView.as_view()),
    path("tag-usage/", asset_usage_count, name="tag-usage"),
    path("clear-tags/<uuid:asset_id>/", clear_all_tags),
    path("get-new-version-no/<str:asset_code>/", get_new_version_no),
    path("get-all-file-versions/<str:asset_code>/", get_all_file_versions),
    path("delete-asset-by-code/<str:asset_code>/", delete_asset_by_code),
]
