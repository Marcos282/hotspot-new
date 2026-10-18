import re
from decimal import Decimal
from django import forms
from django.core import signing
from tenants.models import AccessPlan, Device


class PriceField(forms.DecimalField):
    widget = forms.TextInput

    def __init__(self, **kwargs):
        kwargs.setdefault('label', 'Preço (R$)')
        kwargs.setdefault('max_digits', 10)
        kwargs.setdefault('decimal_places', 2)
        kwargs.setdefault('min_value', Decimal('0'))
        kwargs.setdefault('help_text', 'Digite, por exemplo, 10, 10,50 ou 10.50.')
        kwargs.setdefault('widget', forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': '0,00', 'autocomplete': 'off'}))
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace('\xa0', '').replace(' ', '')
            if value.startswith('R$'):
                value = value[2:]
            if ',' in value and '.' in value:
                if not re.fullmatch(r'\d{1,3}(?:\.\d{3})+,\d{1,2}', value):
                    raise forms.ValidationError('Informe um preço como 10,50 ou 10.50.')
                value = value.replace('.', '')
            if not re.fullmatch(r'\d+(?:[.,]\d{1,2})?', value):
                raise forms.ValidationError('Informe um preço como 10,50 ou 10.50.')
            value = value.replace(',', '.')
        return super().to_python(value)


class HotspotAccessForm(forms.Form):
    guest_name = forms.CharField(label='Nome do cliente', max_length=100)
    username = forms.RegexField(label='Usuário do Hotspot', regex=r'\A[A-Za-z0-9][A-Za-z0-9._-]{2,39}\Z', max_length=40,
        widget=forms.TextInput(attrs={'autocomplete':'off','autocapitalize':'none','spellcheck':'false'}))
    password = forms.CharField(label='Senha do Hotspot', min_length=8, max_length=64, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    plan = forms.ModelChoiceField(label='Plano de acesso', queryset=AccessPlan.objects.none())
    devices = forms.TypedChoiceField(label='Dispositivos simultâneos', coerce=int, choices=[(n,str(n)) for n in range(1,7)], initial=1)
    device = forms.ModelChoiceField(label='MikroTik do estabelecimento', queryset=Device.objects.none())
    request_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, tenant, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant, self.user = tenant, user
        self.fields['plan'].queryset = AccessPlan.objects.for_tenant(tenant).filter(enabled=True, duration_minutes__in=[60,180,360]).order_by('duration_minutes','price')
        self.fields['device'].queryset = Device.objects.for_tenant(tenant).filter(enabled=True).order_by('name')
        if self.fields['device'].queryset.count() == 1:
            self.initial['device'] = self.fields['device'].queryset.first().pk
        self.fields['plan'].label_from_instance = lambda plan: f'{plan.name} · {plan.duration_minutes // 60} h · R$ {plan.price:.2f}'.replace('.', ',')
        if not self.is_bound:
            import uuid
            self.initial['request_token'] = signing.dumps({'tenant':tenant.pk,'user':user.pk,'nonce':str(uuid.uuid4())}, salt='hotspot-access')

    def clean(self):
        import uuid
        values = super().clean()
        try:
            token = signing.loads(values.get('request_token',''),salt='hotspot-access',max_age=900)
            if token['tenant'] != self.tenant.pk or token['user'] != self.user.pk:
                raise ValueError
            values['request_id'] = uuid.UUID(token['nonce'])
        except (signing.BadSignature, KeyError, ValueError, TypeError):
            raise forms.ValidationError('Formulário expirado. Atualize a página e tente novamente.')
        return values
