from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from website.views import HomeView, LeadRequestView


urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("demonstracao/", LeadRequestView.as_view(), name="demo-request"),
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("painel/", include("tenants.urls")),
]
