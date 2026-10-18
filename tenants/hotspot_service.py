import hashlib
import ipaddress
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from operations.routeros import RouterOSClient, RouterOSError
from operations.security import encrypt_secret, decrypt_secret
from tenants.models import HotspotAccess, AuditEvent, AccessPlan, Device


class HotspotClient(RouterOSClient):
    # The shared monitoring adapter stays read-only. Writes here are fixed,
    # scoped Hotspot operations reached only after an authorized POST.
    def create_access(self, access, password, speed_limit):
        duration = f'{access.duration_minutes // 60}h'
        digest = hashlib.sha256(speed_limit.encode()).hexdigest()[:8]
        profile = f'ni-{access.tenant_id}-{access.duration_minutes}-{access.devices}-{digest}'
        existing = self._command(['/ip/hotspot/user/print', '?name='+access.username, '=.proplist=name'])
        if existing:
            raise RouterOSError('Nome já existente no roteador.')
        profiles = self._command(['/ip/hotspot/user/profile/print','?name='+profile,'=.proplist=name,shared-users,session-timeout,rate-limit'])
        if profiles:
            row = profiles[0]
            if (row.get('shared-users') != str(access.devices) or
                row.get('session-timeout') not in (duration,f'{access.duration_minutes // 60:02}:00:00') or
                row.get('rate-limit','') != speed_limit):
                raise RouterOSError('Perfil precisa de conferência técnica.')
        else:
            self._command(['/ip/hotspot/user/profile/add','=name='+profile,'=shared-users='+str(access.devices),
                           '=session-timeout='+duration,'=rate-limit='+speed_limit,'=add-mac-cookie=no'])
        self._command(['/ip/hotspot/user/add','=name='+access.username,'=password='+password,
                       '=profile='+profile,'=limit-uptime='+duration,'=comment=Nova Info '+str(access.request_id)])


def connected_client(device):
    peer = getattr(device, 'vpn_peer', None)
    if not device.enabled or not peer or not peer.enabled or device.management_ip != peer.vpn_ip:
        raise RouterOSError('MikroTik desconectado ou sem vínculo WireGuard autorizado.')
    ip = ipaddress.ip_address(device.management_ip)
    if not ip.is_private or ip.is_loopback or ip.is_link_local:
        raise RouterOSError('IP do túnel inválido.')
    return HotspotClient(device, getattr(settings,'HOTSPOT_WIREGUARD_INTERFACE','wg0'))


def issue_access(tenant, user, values):
    previous = HotspotAccess.objects.for_tenant(tenant).filter(request_id=values['request_id']).first()
    if previous:
        if previous.status == 'active' and previous.created_by_id == user.pk:
            return previous, decrypt_secret(previous.encrypted_password)
        raise RouterOSError('Solicitação já recebida. Solicite conferência antes de tentar novamente.')
    plan = AccessPlan.objects.for_tenant(tenant).get(pk=values['plan'].pk,enabled=True,duration_minutes__in=[60,180,360])
    device = Device.objects.for_tenant(tenant).select_related('vpn_peer').get(pk=values['device'].pk,enabled=True)
    if HotspotAccess.objects.for_tenant(tenant).filter(device=device,username=values['username']).exists():
        raise RouterOSError('Este usuário já existe neste MikroTik. Escolha outro nome.')
    encrypted = encrypt_secret(values['password'])
    with connected_client(device) as client:
        if not client.read('/system/resource/print',['uptime']):
            raise RouterOSError('O roteador não confirmou disponibilidade.')
        with transaction.atomic():
            try:
                access, created = HotspotAccess.objects.get_or_create(tenant=tenant,request_id=values['request_id'], defaults={
                    'device':device,'plan':plan,'created_by':user,'guest_name':values['guest_name'],
                    'username':values['username'],'encrypted_password':encrypted,'devices':values['devices'],
                    'duration_minutes':plan.duration_minutes,
                })
            except IntegrityError:
                raise RouterOSError('Nome ou solicitação já utilizados. Atualize a página.') from None
            if not created:
                raise RouterOSError('Solicitação em processamento; não repita a criação.')
            try:
                client.create_access(access,values['password'],plan.speed_limit)
            except (RouterOSError, OSError):
                access.status = 'uncertain'
            else:
                access.status = 'active'
            access.save(update_fields=['status'])
            AuditEvent.objects.create(tenant=tenant,actor=user,action='criar acesso' if access.status=='active' else 'conferir criação de acesso',object_type='hotspotaccess',object_id=access.pk,fields_changed=['username','devices','duration_minutes','status'])
    if access.status != 'active':
        raise RouterOSError('Não foi possível confirmar a criação. Solicite conferência técnica antes de tentar novamente.')
    return access, values['password']
