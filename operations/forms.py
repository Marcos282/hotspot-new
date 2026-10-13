import re
from django import forms
from django.core.exceptions import ValidationError, ImproperlyConfigured
from operations.models import NetworkConfiguration, WireGuardPeer
from operations.security import encrypt_secret
from tenants.forms import DeviceForm
from tenants.models import Tenant, Device, TenantMembership


class EstablishmentForm(forms.ModelForm):
    class Meta:
        model=Tenant
        fields=['name','slug','legal_name','responsible_name','email','phone','city','state','is_active']


class CentralDeviceForm(DeviceForm):
    api_password=forms.CharField(label='Nova senha API-SSL (não será exibida novamente)',required=False,widget=forms.PasswordInput(render_value=False),max_length=256)

    class Meta(DeviceForm.Meta):
        fields=['tenant',*DeviceForm.Meta.fields,'api_username','certificate_sha256','monitoring_enabled','session_collection_enabled','privacy_purpose']

    def clean(self):
        values=super().clean()
        if self.instance.pk and 'tenant' in self.changed_data:
            raise ValidationError('Não é permitido mover equipamentos entre estabelecimentos. Cadastre outro equipamento.')
        version=values.get('routeros_version','')
        if values.get('monitoring_enabled'):
            match=re.fullmatch(r'([67])\.(\d+)(?:\.\d+)?[a-zA-Z0-9.-]*',version)
            if not match or (match[1]=='6' and int(match[2])<43):
                self.add_error('routeros_version','O adaptador API exige RouterOS 6.43+ ou 7. Informe a versão instalada.')
        fingerprint=values.get('certificate_sha256','').lower()
        if fingerprint and not re.fullmatch('[0-9a-f]{64}',fingerprint):
            self.add_error('certificate_sha256','Informe os 64 caracteres hexadecimais do SHA-256.')
        values['certificate_sha256']=fingerprint
        if values.get('session_collection_enabled') and not values.get('privacy_purpose'):
            self.add_error('privacy_purpose','Documente a finalidade e base legal antes da coleta.')
        if values.get('session_collection_enabled'):
            config=NetworkConfiguration.objects.filter(pk=1).first()
            if not config or not config.session_retention_days:
                self.add_error('session_collection_enabled','Defina primeiro a retenção de sessões na configuração central.')
        if values.get('api_password'):
            try:
                self.encrypted_password=encrypt_secret(values['api_password'])
            except ImproperlyConfigured:
                self.add_error('api_password','Configure a chave de criptografia no ambiente do servidor antes de salvar uma senha.')
        return values

    def save(self,commit=True):
        obj=super().save(commit=False)
        if getattr(self,'encrypted_password',None):
            obj.api_password_encrypted=self.encrypted_password
        if commit:
            obj.save()
        return obj


class NetworkForm(forms.ModelForm):
    class Meta:
        model=NetworkConfiguration
        exclude=[]

    def clean(self):
        values=super().clean()
        if self.instance.pk and WireGuardPeer.objects.exists() and any(field in self.changed_data for field in ['network','server_ip','public_key','interface']):
            raise ValidationError('Com peers cadastrados, mudanças de rede, interface ou chave exigem migração manual revisada.')
        return values


class PeerForm(forms.Form):
    device=forms.ModelChoiceField(label='Equipamento',queryset=Device.objects.none())
    public_key=forms.CharField(label='Chave pública do MikroTik ou gateway',max_length=44)
    vpn_ip=forms.GenericIPAddressField(label='IP VPN desejado (opcional; vazio reserva automaticamente)',protocol='IPv4',required=False)
    use_vpn_ip=forms.BooleanField(label='Usar o IP reservado como IP de gerência deste equipamento',required=False,initial=True)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['device'].queryset=Device.objects.filter(vpn_peer__isnull=True,enabled=True,tenant__is_active=True).select_related('tenant').order_by('tenant__name','name')

    def clean_public_key(self):
        from operations.models import validate_public_key
        value=self.cleaned_data['public_key']
        validate_public_key(value)
        return value


class MembershipForm(forms.ModelForm):
    class Meta:
        model=TenantMembership
        fields=['tenant','user','role','is_active']
