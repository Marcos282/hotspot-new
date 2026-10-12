from django.urls import path

from tenants.views import DashboardView


app_name = "tenants"
urlpatterns = [path("", DashboardView.as_view(), name="dashboard")]
