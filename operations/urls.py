from django.urls import path
from django.contrib.auth.views import LoginView
from operations import views

app_name='operations'
urlpatterns=[
    path('login/',LoginView.as_view(template_name='operations/login.html',next_page='/central/'),name='login'),
    path('',views.dashboard,name='dashboard'),
    path('configuracoes/',views.configuration,name='configuration'),
    path('wireguard/',views.peers,name='peers'),
    path('wireguard/novo/',views.peer_create,name='peer-create'),
    path('wireguard/<int:pk>/revogar/',views.peer_revoke,name='peer-revoke'),
    path('wireguard/<int:pk>/<slug:kind>/download/',views.peer_download,name='peer-download'),
    path('conexoes/',views.connections,name='connections'),
    path('relatorios/',views.reports,name='reports'),
    path('alertas/<int:pk>/reconhecer/',views.acknowledge_alert,name='alert-acknowledge'),
    path('<slug:section>/novo/',views.edit,name='create'),
    path('<slug:section>/<int:pk>/editar/',views.edit,name='edit'),
    path('<slug:section>/',views.records,name='records'),
]
