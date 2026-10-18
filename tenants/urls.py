from django.urls import path
from tenants.cash import CashSaleView
from operations.subscription_views import SubscriptionView
from tenants.views import TenantReportView, HotspotPreviewView, DashboardView, RecordsView, RecordEditView, HotspotView, ImagesView, ImageView

from tenants.status import StatusView
from tenants.panel_views import CreateHotspotAccessView, OnlineUsersView, MyAccountView

app_name = 'tenants'
urlpatterns = [
    path('criar-acesso/', CreateHotspotAccessView.as_view(), name='create-access'),
    path('usuarios-online/', OnlineUsersView.as_view(), name='online'),
    path('online/', OnlineUsersView.as_view(), name='legacy-online'),
    path('minha-conta/', MyAccountView.as_view(), name='my-account'),
    path('', DashboardView.as_view(), name='dashboard'),
    path('status/', StatusView.as_view(), name='status'),
    path('vendas/dinheiro/', CashSaleView.as_view(), name='cash-sale'),
    path('assinatura/', SubscriptionView.as_view(), name='subscription'),
    path('relatorios/', TenantReportView.as_view(), name='reports'),
    path('hotspot/previa/', HotspotPreviewView.as_view(), name='hotspot-preview'),
    path('hotspot/', HotspotView.as_view(), name='hotspot'),
    path('imagens/', ImagesView.as_view(), name='images'),
    path('imagens/<int:pk>/', ImageView.as_view(), name='image'),
    path('<slug:section>/novo/', RecordEditView.as_view(), name='create'),
    path('<slug:section>/<int:pk>/editar/', RecordEditView.as_view(), name='edit'),
    path('<slug:section>/', RecordsView.as_view(), name='records'),
]
