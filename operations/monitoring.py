from datetime import datetime, timedelta, timezone as utc
import ipaddress
import re
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from operations.models import NetworkConfiguration, DeviceHealth, HealthSample, Outage, DeviceAlert
from operations.routeros import RouterOSClient, RouterOSError
from operations.wireguard import snapshot, WireGuardError
from tenants.models import Device, AccessSession


def duration_seconds(value):
    if re.fullmatch(r'\d+:\d{2}:\d{2}', value):
        hours, minutes, seconds = map(int,value.split(':'))
        return hours*3600 + minutes*60 + seconds
    parts = re.findall(r'(\d+)([wdhms])', value)
    if ''.join(number+unit for number,unit in parts) != value:
        return 0
    return sum(int(number)*{'w':604800,'d':86400,'h':3600,'m':60,'s':1}[unit] for number,unit in parts)


def sync_sessions(device, rows, now):
    active = []
    for row in rows:
        session_id = row.get('.id','')[:120]
        if not session_id:
            continue
        session = AccessSession.objects.for_tenant(device.tenant).filter(device=device,router_session_id=session_id,ended_at__isnull=True).first()
        if session is None:
            session = AccessSession(tenant=device.tenant,device=device,router_session_id=session_id,started_at=now-timedelta(seconds=min(duration_seconds(row.get('uptime','')),10*365*86400)))
        session.username = row.get('user','')[:120]
        try:
            session.bytes_used = max(0,int(row.get('bytes-in',0))) + max(0,int(row.get('bytes-out',0)))
            if session.bytes_used > 2**63-1:
                session.bytes_used = 2**63-1
        except (ValueError,TypeError):
            session.bytes_used = 0
        session.last_seen = now
        session.save()
        active.append(session.pk)
    AccessSession.objects.for_tenant(device.tenant).filter(device=device,ended_at__isnull=True).exclude(pk__in=active).update(ended_at=now)


def track_outage(device, component, status, now, delay):
    current = Outage.objects.for_tenant(device.tenant).filter(device=device,component=component,ended_at__isnull=True).first()
    if status in ('offline','error'):
        if current is None:
            current = Outage.objects.create(tenant=device.tenant,device=device,component=component,started_at=now)
        if (now-current.started_at).total_seconds() >= delay and current.alerted_at is None:
            DeviceAlert.objects.get_or_create(outage=current,defaults={'tenant':device.tenant})
            current.alerted_at = now
            current.save(update_fields=['alerted_at'])
    elif status == 'online' and current:
        current.ended_at = now
        current.save(update_fields=['ended_at'])


def probe_device(device, config, wg_data, now=None, client_class=RouterOSClient):
    now = now or timezone.now()
    peer = getattr(device,'vpn_peer',None)
    vpn_status = api_status = hotspot_status = 'waiting'
    vpn_detail = api_detail = hotspot_detail = 'Aguardando configuração'
    handshake = None
    session_rows = None
    if peer and not peer.enabled:
        vpn_status = 'revoked'
        vpn_detail = peer.lifecycle_label
        api_detail = hotspot_detail = 'Monitoramento suspenso por revogação'
    elif device.enabled and device.monitoring_enabled and peer:
        if wg_data is None:
            vpn_status = 'unknown'
            vpn_detail = 'Leitura do WireGuard indisponível'
        else:
            handshakes, routes = wg_data
            allowed = routes.get(peer.public_key, [])
            stamp = handshakes.get(peer.public_key,0)
            if peer.public_key not in routes:
                vpn_detail = 'Peer ainda não aplicado no servidor'
            elif not any(ipaddress.ip_address(peer.vpn_ip) in network for network in allowed):
                vpn_status = 'error'
                vpn_detail = 'Rotas do peer diferentes da configuração'
            elif stamp > 0:
                handshake = datetime.fromtimestamp(stamp, tz=utc.utc)
                vpn_status = 'online' if 0 <= (now-handshake).total_seconds() <= 180 else 'offline'
                vpn_detail = 'Handshake recente' if vpn_status=='online' else 'Handshake fora da janela de 180 segundos'
            else:
                vpn_status = 'offline'
                vpn_detail = 'Peer aplicado, sem handshake observado'
        if vpn_status == 'online':
            if device.management_ip != peer.vpn_ip:
                api_detail = 'Configure o IP de gerência igual ao IP reservado da VPN'
            elif not device.api_username or not device.api_password_encrypted:
                api_detail = 'Credenciais API-SSL não configuradas'
            else:
                try:
                    with client_class(device, config.interface) as client:
                        resources = client.read('/system/resource/print',['version'])
                        if not resources:
                            raise RouterOSError('Sem resposta de recursos')
                        api_status = 'online'
                        api_detail = 'API-SSL autenticada pela VPN'
                        try:
                            hotspots = client.read('/ip/hotspot/print',['.id','disabled','invalid'])
                            hotspot_status = 'online' if any(row.get('disabled','false')=='false' and row.get('invalid','false')=='false' for row in hotspots) else 'offline'
                            hotspot_detail = 'Servidor Hotspot habilitado' if hotspot_status=='online' else 'Nenhum servidor Hotspot válido habilitado'
                            if device.session_collection_enabled and device.privacy_purpose and config.session_retention_days:
                                session_rows = client.read('/ip/hotspot/active/print',['.id','user','uptime','bytes-in','bytes-out'])
                        except (RouterOSError,OSError):
                            hotspot_status = 'error'
                            hotspot_detail = 'Consulta Hotspot recusada ou interrompida'
                except (RouterOSError,OSError):
                    api_status = 'offline'
                    api_detail = 'API-SSL indisponível, certificado ou autenticação recusados'
                except Exception:
                    # Do not persist exception values or router responses containing credentials.
                    api_status = 'error'
                    api_detail = 'Não foi possível validar a configuração de credenciais'
        elif vpn_status in ('offline','error','unknown'):
            api_status = hotspot_status = 'unknown'
            api_detail = hotspot_detail = 'Não consultado: VPN sem confirmação recente'
    with transaction.atomic():
        # Serialize overlapping worker runs per device.
        Device.objects.select_for_update().get(pk=device.pk)
        health,_ = DeviceHealth.objects.get_or_create(tenant=device.tenant,device=device)
        for field,value in dict(vpn_status=vpn_status,api_status=api_status,hotspot_status=hotspot_status,vpn_detail=vpn_detail,api_detail=api_detail,hotspot_detail=hotspot_detail,vpn_handshake_at=handshake,checked_at=now).items():
            setattr(health,field,value)
        health.save()
        HealthSample.objects.create(tenant=device.tenant,device=device,vpn_status=vpn_status,api_status=api_status,hotspot_status=hotspot_status,checked_at=now)
        if api_status=='online':
            Device.objects.filter(pk=device.pk).update(last_seen=now)
        for component,status in [('vpn',vpn_status),('api',api_status),('hotspot',hotspot_status)]:
            track_outage(device,component,status,now,config.disconnect_after_seconds)
        if session_rows is not None:
            sync_sessions(device,session_rows,now)
    return health


def poll_all():
    config = NetworkConfiguration.objects.filter(pk=1).first()
    if config is None:
        return 0
    config.full_clean()
    try:
        wg_data = snapshot(config.interface)
    except WireGuardError:
        wg_data = None
    count = 0
    for device in Device.objects.filter(enabled=True).select_related('tenant','vpn_peer'):
        probe_device(device,config,wg_data)
        count += 1
    return count


def monthly_availability(device, now=None):
    now = now or timezone.now()
    start = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    samples = list(HealthSample.objects.for_tenant(device.tenant).filter(device=device,checked_at__gte=start,checked_at__lte=now).order_by('checked_at'))
    result = {'coverage_seconds':0}
    for component in ['vpn','api','hotspot']:
        result[component+'_coverage_seconds'] = 0
        result[component+'_online_seconds'] = 0
    for index,sample in enumerate(samples):
        end = samples[index+1].checked_at if index+1<len(samples) else now
        interval = (end-sample.checked_at).total_seconds()
        seconds = min(max(0,interval),settings.MONITOR_MAX_GAP_SECONDS)
        for component in ['vpn','api','hotspot']:
            status=getattr(sample,component+'_status')
            if status in ('online','offline','error'):
                result[component+'_coverage_seconds'] += seconds
                if status=='online':
                    result[component+'_online_seconds'] += seconds
    for component in ['vpn','api','hotspot']:
        coverage=result[component+'_coverage_seconds']
        result[component+'_percent']=round(100*result[component+'_online_seconds']/coverage,2) if coverage else None
    result['coverage_seconds']=result['vpn_coverage_seconds']
    total=(now-start).total_seconds()
    result['month_coverage_percent']=round(100*result['coverage_seconds']/total,2) if total else 0
    return result
