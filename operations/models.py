import base64
import uuid
import ipaddress
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from tenants.models import TenantOwnedModel, Device


def validate_public_key(value):
    try:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) != 32 or decoded == bytes(32) or base64.b64encode(decoded).decode() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError('Informe uma chave pública WireGuard válida de 32 bytes em base64.')


class NetworkConfiguration(models.Model):
    # A singleton serializes address allocation through SELECT FOR UPDATE.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    endpoint = models.CharField('Host público do servidor WireGuard', max_length=253)
    port = models.PositiveIntegerField('Porta UDP', default=51820, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    interface = models.CharField('Interface do servidor', max_length=15, default='wg0')
    network = models.CharField('Rede VPN IPv4', max_length=18, default='10.77.0.0/24')
    server_ip = models.GenericIPAddressField('IP do servidor na VPN', protocol='IPv4', default='10.77.0.1')
    public_key = models.CharField('Chave pública do servidor', max_length=44, validators=[validate_public_key])
    disconnect_after_seconds = models.PositiveIntegerField('Atraso para alerta (segundos)', default=300, validators=[MinValueValidator(60)])
    session_retention_days = models.PositiveIntegerField('Retenção de sessões encerradas (dias)', null=True, blank=True, validators=[MinValueValidator(1)], help_text='Sem valor, o expurgo fica desativado. Defina prazo compatível com sua finalidade e obrigações.')
    audit_retention_days = models.PositiveIntegerField('Retenção da auditoria (dias)', null=True, blank=True, validators=[MinValueValidator(1)])
    monitoring_retention_days = models.PositiveIntegerField('Retenção das amostras (dias)', null=True, blank=True, validators=[MinValueValidator(1)])

    class Meta:
        permissions = [('manage_network', 'Gerenciar a central de rede e todos os estabelecimentos')]

    def clean(self):
        try:
            network = ipaddress.ip_network(self.network, strict=True)
            server = ipaddress.ip_address(self.server_ip)
            if network.version != 4 or network.prefixlen < 16 or network.prefixlen > 29 or server not in network or server in (network.network_address, network.broadcast_address):
                raise ValueError()
            if not any(network.subnet_of(ipaddress.ip_network(block)) for block in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
                raise ValueError()
        except ValueError:
            raise ValidationError('Use uma rede VPN privada IPv4 /16 a /29 e um IP válido dentro dela.')
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', self.endpoint):
            raise ValidationError('Informe apenas o host do endpoint, sem protocolo, porta ou comandos.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', self.interface):
            raise ValidationError('Interface inválida.')


class WireGuardPeer(TenantOwnedModel):
    device = models.OneToOneField(Device, on_delete=models.PROTECT, related_name='vpn_peer')
    public_key = models.CharField('Chave pública do equipamento/gateway', max_length=44, unique=True, validators=[validate_public_key])
    vpn_ip = models.GenericIPAddressField('IP reservado da VPN', protocol='IPv4', unique=True)
    enabled = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    removal_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.device_id and self.device.tenant_id != self.tenant_id:
            raise ValidationError('O equipamento deve pertencer ao mesmo estabelecimento.')

    @property
    def lifecycle_label(self):
        if not self.enabled:
            return 'Removido em runtime · revisar persistência' if self.removal_confirmed_at else 'Revogação solicitada · remoção pendente'
        return 'Cadastrado · aplicação no servidor depende de revisão'


class DeviceHealth(TenantOwnedModel):
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name='health')
    vpn_status = models.CharField(max_length=20, default='waiting')
    api_status = models.CharField(max_length=20, default='waiting')
    hotspot_status = models.CharField(max_length=20, default='waiting')
    vpn_handshake_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    vpn_detail = models.CharField(max_length=100, blank=True)
    api_detail = models.CharField(max_length=100, blank=True)
    hotspot_detail = models.CharField(max_length=100, blank=True)


class HealthSample(TenantOwnedModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    vpn_status = models.CharField(max_length=20)
    api_status = models.CharField(max_length=20)
    hotspot_status = models.CharField(max_length=20)
    checked_at = models.DateTimeField(default=timezone.now, db_index=True)


class Outage(TenantOwnedModel):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    component = models.CharField(max_length=16, choices=[('vpn','VPN'),('api','API RouterOS'),('hotspot','Hotspot')])
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['device','component'], condition=models.Q(ended_at__isnull=True), name='one_open_outage_per_component')]


class DeviceAlert(TenantOwnedModel):
    outage = models.OneToOneField(Outage, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)


class ControlAuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=120)
    fields_changed = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class SaaSSubscription(TenantOwnedModel):
    class Meta:
        constraints=[models.CheckConstraint(condition=models.Q(monthly_amount__gt=0),name='saas_positive_monthly_amount')]

    tenant = models.OneToOneField('tenants.Tenant',on_delete=models.PROTECT,related_name='saas_subscription')
    plan = models.ForeignKey('website.SubscriptionPlan',on_delete=models.PROTECT)
    external_id = models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    monthly_amount = models.DecimalField(max_digits=10,decimal_places=2)
    payer_email = models.EmailField()
    provider_reference = models.CharField(max_length=64,blank=True)
    checkout_url = models.URLField(max_length=512,blank=True)
    status = models.CharField(max_length=20,default='requested',choices=[('requested','Solicitada'),('creating','Em processamento'),('pending','Aguardando autorização'),('authorized','Recorrência autorizada'),('paused','Pausada'),('cancelled','Cancelada'),('error','Revisão necessária')])
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
