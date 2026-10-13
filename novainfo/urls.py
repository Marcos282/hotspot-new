from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from operations.webhooks import subscription_webhook
from tenants.account import AccountView, TenantLoginView

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
    path("minha-conta/", AccountView.as_view(), name="account"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("painel/", include("tenants.urls")),
]
