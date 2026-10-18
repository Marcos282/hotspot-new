from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from tenants.mixins import TenantAccessMixin
from tenants.models import Device
from tenants.panel_forms import HotspotAccessForm
from tenants.hotspot_service import issue_access, connected_client
from operations.routeros import RouterOSError


def page(request, title, template, **extra):
    return render(request,template,{'tenant':request.tenant,'membership':request.tenant_membership,'page_title':title,**extra})


@method_decorator(never_cache,name='dispatch')
class CreateHotspotAccessView(TenantAccessMixin, View):
    def handle(self,request):
        if request.tenant_membership.role not in ['owner','admin','staff']:
            raise PermissionDenied
        form = HotspotAccessForm(request.POST if request.method=='POST' else None,tenant=request.tenant,user=request.user)
        if request.method=='POST' and form.is_valid():
            try:
                access,password = issue_access(request.tenant,request.user,form.cleaned_data)
            except RouterOSError as exc:
                form.add_error(None,str(exc))
            except (ImproperlyConfigured,OSError):
                form.add_error(None,'MikroTik indisponível. Peça ao administrador que confira o túnel, o certificado e as permissões da API.')
            else:
                hours = access.duration_minutes // 60
                text=f'Wi-Fi {request.tenant.name}\nUsuário: {access.username}\nSenha: {password}\nTempo de uso: {hours} h\nDispositivos simultâneos: {access.devices}'
                return page(request,'Acesso criado','tenants/access_created.html',access=access,password=password,hours=hours,whatsapp='https://wa.me/?'+urlencode({'text':text}))
        return page(request,'Criar Acesso','tenants/create_access.html',form=form)
    get=handle
    post=handle


@method_decorator(never_cache,name='dispatch')
class OnlineUsersView(TenantAccessMixin, View):
    def get(self,request):
        rows=[]
        devices=list(Device.objects.for_tenant(request.tenant).filter(enabled=True).select_related('vpn_peer'))
        error=''
        try:
            if not devices:
                raise RouterOSError()
            for device in devices:
                if not device.session_collection_enabled or not device.privacy_purpose:
                    raise RouterOSError()
                with connected_client(device) as client:
                    live=client.read('/ip/hotspot/active/print',['user','address','uptime'])
                rows.extend({'username':row.get('user','')[:120],'ip':row.get('address','')[:50],'uptime':row.get('uptime','')[:50]} for row in live)
        except (RouterOSError,OSError,ImproperlyConfigured):
            rows=[]
            error='MikroTik desconectado — Não foi possível consultar os usuários.'
        return page(request,'Usuários Online','tenants/online.html',rows=rows,error=error,checked_at=timezone.now())


@method_decorator(never_cache,name='dispatch')
class MyAccountView(TenantAccessMixin, View):
    def handle(self,request):
        form=PasswordChangeForm(request.user,request.POST if request.method=='POST' else None)
        if request.method=='POST' and form.is_valid():
            update_session_auth_hash(request,form.save())
            messages.success(request,'Senha alterada.')
            return redirect('tenants:my-account')
        return page(request,'Minha Conta','tenants/account.html',form=form)
    get=handle
    post=handle
