from datetime import datetime, timedelta
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.debug import sensitive_post_parameters
from operations.forms import EstablishmentForm, CentralDeviceForm, NetworkForm, PeerForm, MembershipForm
from operations.models import NetworkConfiguration, WireGuardPeer, DeviceHealth, DeviceAlert, HealthSample, Outage, ControlAuditEvent, SaaSSubscription
from operations.wireguard import allocate_peer, server_configuration, client_configuration, routeros_script
from operations.monitoring import monthly_availability
from tenants.models import Tenant, TenantMembership, Device, AccessPlan, Sale, Payment, AccessSession, HotspotConfiguration, BrandImage, AuditEvent
from tenants.views import audit


LABELS={'waiting':'Aguardando configuração','online':'Online','offline':'Offline','unknown':'Sem confirmação','error':'Erro na verificação','revoked':'Revogado / remoção pendente'}


def central_access(function):
    @login_required(login_url='/accounts/painel/login/')
    @wraps(function)
    def protected(request,*args,**kwargs):
        if not getattr(request,'platform_host',False) or request.tenant is not None or not request.user.is_active or not request.user.is_staff or not request.user.has_perm('operations.manage_network'):
            raise PermissionDenied
        return function(request,*args,**kwargs)
    return protected


def context(request,title,**kwargs):
    return dict(page_title=title,central=True,**kwargs)


def state(device):
    health=getattr(device,'health',None)
    now=timezone.now()
    fresh=health and health.checked_at and (now-health.checked_at).total_seconds()<=300
    def component(name):
        if health is None:
            return LABELS['waiting']
        value=getattr(health,name+'_status')
        if not fresh and value not in ('waiting','revoked'):
            return 'Sem confirmação recente'
        return LABELS.get(value,value)
    return {'device':device,'vpn':component('vpn'),'api':component('api'),'hotspot':component('hotspot'),'checked_at':health.checked_at if health else None}


@central_access
def dashboard(request):
    devices=Device.objects.select_related('tenant','health','vpn_peer').order_by('tenant__name','name')
    page=Paginator(devices,50).get_page(request.GET.get('page'))
    now=timezone.now()
    online=DeviceHealth.objects.filter(vpn_status='online',checked_at__gte=now-timedelta(minutes=5)).count()
    alerts=DeviceAlert.objects.filter(acknowledged_at__isnull=True).select_related('outage__device','tenant').order_by('-created_at')[:20]
    from operations.server_status import wireguard_server_status
    config=NetworkConfiguration.objects.filter(pk=1).first()
    return render(request,'operations/dashboard.html',context(request,'Central de controle',states=[state(device) for device in page],page_obj=page,tenant_count=Tenant.objects.count(),device_count=devices.count(),online_count=online,alerts=alerts,config=config,wireguard_server=wireguard_server_status(config)))


LISTS={
    'estabelecimentos':(Tenant,'Estabelecimentos',[('name','Estabelecimento'),('slug','Subdomínio'),('city','Cidade'),('is_active','Ativo')],EstablishmentForm),
    'equipamentos':(Device,'Equipamentos MikroTik',[('tenant','Estabelecimento'),('name','Nome'),('management_ip','IP de gerência'),('routeros_version','RouterOS'),('monitoring_enabled','Monitoramento')],CentralDeviceForm),
    'usuarios':(TenantMembership,'Usuários e permissões',[('tenant','Estabelecimento'),('user','Usuário'),('role','Função'),('is_active','Ativo')],MembershipForm),
    'planos':(AccessPlan,'Planos de acesso',[('tenant','Estabelecimento'),('name','Plano'),('duration_minutes','Minutos'),('price','Valor')],None),
    'assinaturas':(SaaSSubscription,'Mensalidades dos estabelecimentos',[('tenant','Estabelecimento'),('plan','Plano'),('monthly_amount','Mensalidade'),('status','Autorização'),('updated_at','Atualização')],None),
    'vendas':(Sale,'Vendas',[('tenant','Estabelecimento'),('reference','Referência'),('amount','Valor'),('status','Situação'),('created_at','Data')],None),
    'pagamentos':(Payment,'Recebimentos em dinheiro dos estabelecimentos',[('tenant','Estabelecimento'),('provider_reference','Referência'),('get_method_display','Forma'),('amount','Valor'),('received_by','Registrado por'),('received_at','Recebido em')],None),
    'hotspot':(HotspotConfiguration,'Hotspot',[('tenant','Estabelecimento'),('title','Título'),('free_access','Acesso gratuito'),('updated_at','Atualização')],None),
    'publicidade':(BrandImage,'Publicidade e logotipos',[('tenant','Estabelecimento'),('title','Descrição'),('kind','Tipo'),('created_at','Data')],None),
    'auditoria-central':(ControlAuditEvent,'Auditoria da central',[('actor','Administrador'),('action','Ação'),('fields_changed','Campos modificados'),('created_at','Data')],None),
    'auditoria':(AuditEvent,'Auditoria',[('tenant','Estabelecimento'),('actor','Administrador'),('action','Ação'),('object_type','Cadastro'),('fields_changed','Campos modificados'),('created_at','Data')],None),
}


@central_access
def records(request,section):
    if section not in LISTS:
        raise Http404
    model,title,columns,form=LISTS[section]
    query=model.objects.order_by('-pk')
    tenant_id=request.GET.get('tenant','')
    if tenant_id:
        try:
            query=query.filter(pk=int(tenant_id)) if model is Tenant else query.filter(tenant_id=int(tenant_id)) if model is not ControlAuditEvent else query.none()
        except ValueError:
            raise Http404
    page=Paginator(query,50).get_page(request.GET.get('page'))
    rows=[dict(pk=obj.pk,values=[getattr(obj,field)() if callable(getattr(obj,field)) else getattr(obj,field) for field,label in columns]) for obj in page]
    return render(request,'operations/records.html',context(request,title,rows=rows,columns=[label for field,label in columns],page_obj=page,section=section,editable=bool(form),tenants=Tenant.objects.order_by('name'),selected_tenant=tenant_id))


@central_access
@sensitive_post_parameters('api_password')
def edit(request,section,pk=None):
    if section not in LISTS or LISTS[section][3] is None:
        raise Http404
    model,title,columns,form_class=LISTS[section]
    obj=get_object_or_404(model,pk=pk) if pk else model()
    form=form_class(request.POST if request.method=='POST' else None,instance=obj)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            obj=form.save()
            tenant=obj if model is Tenant else obj.tenant
            AuditEvent.objects.create(tenant=tenant,actor=request.user,action='editar central' if pk else 'criar central',object_type=obj._meta.model_name,object_id=obj.pk,fields_changed=[field for field in form.changed_data if field != 'api_password'] + (['api_credentials'] if 'api_password' in form.changed_data else []))
        messages.success(request,'Cadastro salvo. Nenhuma alteração foi aplicada ao roteador.')
        return redirect('operations:records',section=section)
    return render(request,'operations/form.html',context(request,title,form=form))


@central_access
def configuration(request):
    obj=NetworkConfiguration.objects.filter(pk=1).first() or NetworkConfiguration(pk=1)
    form=NetworkForm(request.POST if request.method=='POST' else None,instance=obj)
    if request.method=='POST' and form.is_valid():
        form.save()
        from operations.models import ControlAuditEvent
        ControlAuditEvent.objects.create(actor=request.user,action='configurar rede/retenção',fields_changed=form.changed_data)
        messages.success(request,'Configuração central salva. Não houve alteração no WireGuard do servidor.')
        return redirect('operations:configuration')
    return render(request,'operations/form.html',context(request,'Configurações da central',form=form,notice='Informe apenas a chave pública do servidor. A chave privada do WireGuard e a chave de criptografia ficam fora do banco. Retenção deve ser definida conforme a finalidade e as obrigações aplicáveis.'))


@central_access
def peers(request):
    page=Paginator(WireGuardPeer.objects.select_related('tenant','device').order_by('-pk'),50).get_page(request.GET.get('page'))
    return render(request,'operations/peers.html',context(request,'WireGuard · IPs reservados',peers=page,page_obj=page))


@central_access
def peer_create(request):
    form=PeerForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                peer=allocate_peer(form.cleaned_data['device'],form.cleaned_data['public_key'],form.cleaned_data['vpn_ip'] or None)
                changed=['device','public_key','vpn_ip']
                if form.cleaned_data['use_vpn_ip']:
                    Device.objects.filter(pk=peer.device_id).update(management_ip=peer.vpn_ip)
                    changed.append('management_ip')
                AuditEvent.objects.create(tenant=peer.tenant,actor=request.user,action='reservar peer VPN',object_type='wireguardpeer',object_id=peer.pk,fields_changed=changed)
            messages.success(request,'IP reservado. Revise as configurações geradas antes de aplicar. O túnel ainda não foi ativado.')
            return redirect('operations:peers')
        except (ValidationError,NetworkConfiguration.DoesNotExist) as error:
            form.add_error(None,'Configure primeiro o servidor central.' if isinstance(error,NetworkConfiguration.DoesNotExist) else error)
    return render(request,'operations/form.html',context(request,'Cadastrar peer WireGuard',form=form,notice='RouterOS 7: crie uma interface dedicada ni-wg-ID e copie sua chave pública. RouterOS 6: use a chave de um gateway externo. A chave privada permanece no equipamento.'))


@central_access
def peer_revoke(request,pk):
    if request.method!='POST':
        return HttpResponse(status=405)
    with transaction.atomic():
        peer=get_object_or_404(WireGuardPeer.objects.select_for_update(),pk=pk)
        if peer.enabled:
            peer.enabled=False
            peer.revoked_at=timezone.now()
            peer.save(update_fields=['enabled','revoked_at'])
            AuditEvent.objects.create(tenant=peer.tenant,actor=request.user,action='solicitar revogação VPN',object_type='wireguardpeer',object_id=peer.pk,fields_changed=['enabled','revoked_at'])
    messages.success(request,'Revogação solicitada. A remoção efetiva exige o comando revisado no servidor e atualização da configuração persistente. O IP permanece reservado.')
    return redirect('operations:peers')


@central_access
def peer_download(request,pk,kind):
    peer=get_object_or_404(WireGuardPeer.objects.select_related('device'),pk=pk)
    if not peer.enabled:
        raise Http404
    config=get_object_or_404(NetworkConfiguration,pk=1)
    config.full_clean()
    if kind=='server':
        content=server_configuration(peer)
    elif kind=='client':
        content=client_configuration(peer,config)
    elif kind=='routeros':
        try:
            content=routeros_script(peer,config)
        except ValidationError as error:
            return HttpResponse('; '.join(error.messages),status=400,content_type='text/plain; charset=utf-8')
    else:
        raise Http404
    response=HttpResponse(content,content_type='text/plain; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="novainfo-peer-{peer.pk}-{kind}.txt"'
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    return response


@central_access
def acknowledge_alert(request,pk):
    if request.method!='POST':
        return HttpResponse(status=405)
    alert=get_object_or_404(DeviceAlert,pk=pk)
    if not alert.acknowledged_at:
        alert.acknowledged_at=timezone.now()
        alert.save(update_fields=['acknowledged_at'])
        AuditEvent.objects.create(tenant=alert.tenant,actor=request.user,action='reconhecer alerta',object_type='devicealert',object_id=alert.pk,fields_changed=['acknowledged_at'])
    return redirect('operations:dashboard')


@central_access
def connections(request):
    devices=Device.objects.select_related('tenant','health','vpn_peer').order_by('name')
    page=Paginator(devices,50).get_page(request.GET.get('page'))
    return render(request,'operations/connections.html',context(request,'Conexões · VPN, API e Hotspot',states=[state(device) for device in page],page_obj=page))


def report_context(request,tenant=None):
    query=AccessSession.objects.order_by('-started_at')
    devices=Device.objects.order_by('name')
    if tenant:
        query=query.for_tenant(tenant)
        devices=devices.for_tenant(tenant)
    else:
        selected=request.GET.get('tenant','')
        if selected:
            if not selected.isdigit():
                raise Http404
            query=query.filter(tenant_id=int(selected))
            devices=devices.filter(tenant_id=int(selected))
    device_id=request.GET.get('device','')
    if device_id:
        device=get_object_or_404(devices,pk=device_id) if device_id.isdigit() else None
        if not device:
            raise Http404
        query=query.filter(device=device)
    for parameter,lookup in [('start','started_at__gte'),('end','started_at__lt')]:
        value=request.GET.get(parameter,'')
        if value:
            try:
                day=datetime.strptime(value,'%Y-%m-%d')
                if parameter=='end':
                    day+=timedelta(days=1)
                query=query.filter(**{lookup:timezone.make_aware(day)})
            except ValueError:
                raise Http404
    if request.GET.get('online')=='1':
        query=query.filter(ended_at__isnull=True,last_seen__gte=timezone.now()-timedelta(minutes=5))
    page=Paginator(query.select_related('device','tenant'),50).get_page(request.GET.get('page'))
    reports=[]
    for device in devices[:50]:
        reports.append({'device':device,'availability':monthly_availability(device)})
    outages=Outage.objects.filter(device__in=devices).select_related('device','tenant').order_by('-started_at')[:50]
    visible_tenants=[tenant] if tenant else Tenant.objects.order_by('name')
    return dict(outages=outages,sessions=page,page_obj=page,devices=devices,tenants=visible_tenants if tenant is None else [],reports=reports,filters=request.GET,online=request.GET.get('online')=='1')


@central_access
def reports(request):
    return render(request,'operations/reports.html',context(request,'Relatórios e disponibilidade',**report_context(request)))


@central_access
def server_status(request):
    from operations.server_status import wireguard_server_status
    config = NetworkConfiguration.objects.filter(pk=1).first()
    devices = Device.objects.select_related('tenant', 'health').order_by('tenant__name', 'name')
    page = Paginator(devices, 50).get_page(request.GET.get('page'))
    response = render(request, 'operations/status.html', context(
        request, 'Status', wireguard_server=wireguard_server_status(config),
        config=config, states=[state(device) for device in page], page_obj=page,
    ))
    response['Cache-Control'] = 'no-store'
    return response
