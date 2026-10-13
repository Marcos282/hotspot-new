from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from operations.webhooks import subscription_webhook
from operations.accounts import ControlLoginView, accounts_panel, approve_account
from tenants.account import (AccountView, TenantLoginView, SignupView, ConfirmAccountView, TenantPasswordResetView)

from website.views import HomeView, LeadRequestView, PlansView, PolicyView, robots, sitemap


urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("demonstracao/", LeadRequestView.as_view(), name="demo-request"),
    path("planos/", PlansView.as_view(), name="platform-plans"),
    path("privacidade/", PolicyView.as_view(extra_context={"kind": "privacy"}), name="privacy"),
    path("termos/", PolicyView.as_view(extra_context={"kind": "terms"}), name="terms"),
    path("retencao/", PolicyView.as_view(extra_context={"kind": "retention"}), name="retention"),
    path("robots.txt", robots, name="robots"),
    path("sitemap.xml", sitemap, name="sitemap"),
    path("admin/", admin.site.urls),
    path("central/", include("operations.urls")),
    path("integracoes/mercado-pago/assinaturas/webhook/", subscription_webhook, name="mercado-pago-webhook"),
    path(
        "accounts/login/",
        TenantLoginView.as_view(),
        name="login",
    ),
    path("accounts/painel/", accounts_panel, name="accounts-panel"),
    path("accounts/painel/login/", ControlLoginView.as_view(), name="accounts-panel-login"),
    path("accounts/painel/usuarios/<int:pk>/aprovar/", approve_account, name="approve-account"),
    path("accounts/cadastro/", SignupView.as_view(), name="signup"),
    path("accounts/confirmar/<str:token>/", ConfirmAccountView.as_view(), name="account-confirm"),
    path("accounts/recuperar/", TenantPasswordResetView.as_view(), name="password_reset"),
    path("accounts/recuperar/enviado/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("accounts/redefinir/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("accounts/redefinir/concluido/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("minha-conta/", AccountView.as_view(), name="account"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("painel/", include("tenants.urls")),
]
