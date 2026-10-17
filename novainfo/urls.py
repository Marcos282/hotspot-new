from operations.views import server_status
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from operations.webhooks import subscription_webhook
from operations.accounts import ControlLoginView, accounts_panel, approve_account, approve_tenant_registration
from tenants.account import (EmailAdminAuthenticationForm, WorkspaceLoginView, AccountView, TenantLoginView, SignupView, TenantRegistrationView, ConfirmAccountView, TenantPasswordResetView)

from website.views import HomeView, LeadRequestView, PlansView, PolicyView, ViaZapView, TaCombinadoView, NovaRedeView, robots, sitemap


admin.site.login_form = EmailAdminAuthenticationForm

urlpatterns = [
    path("accounts/painel/status/", server_status, name="accounts-status"),
    path("accounts/painel/status", server_status),
    path("", HomeView.as_view(), name="home"),
    path("solucoes/novarede/", NovaRedeView.as_view(), name="novarede"),
    path("solucoes/tacombinado/", TaCombinadoView.as_view(), name="tacombinado"),
    path("solucoes/viazap/", ViaZapView.as_view(), name="viazap"),
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
    path("accounts/painel/cadastros/<int:pk>/aprovar/", approve_tenant_registration, name="approve-tenant-registration"),
    path("accounts/painel/usuarios/<int:pk>/aprovar/", approve_account, name="approve-account"),
    path("registro/", TenantRegistrationView.as_view(), name="tenant-register"),
    path("registro", TenantRegistrationView.as_view()),
    path("accounts/cadastro/", SignupView.as_view(), name="signup"),
    path("accounts/confirmar/<str:token>/", ConfirmAccountView.as_view(), name="account-confirm"),
    path("accounts/recuperar/", TenantPasswordResetView.as_view(), name="password_reset"),
    path("accounts/recuperar/enviado/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("accounts/redefinir/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("accounts/redefinir/concluido/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("accounts/entrar/<str:ticket>/", WorkspaceLoginView.as_view(), name="workspace-login"),
    path("minha-conta/", AccountView.as_view(), name="account"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("painel/", include("tenants.urls")),
]
