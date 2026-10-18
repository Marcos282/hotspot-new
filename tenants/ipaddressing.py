import ipaddress
from django import forms


MANAGEMENT_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    '100.64.0.0/10',  # Shared/CGNAT addressing used by private provider networks.
    'fc00::/7',
))


def allowed_management_ip(value):
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return any(address in network for network in MANAGEMENT_NETWORKS)
    except ValueError:
        return False


class PrivateManagementIPField(forms.GenericIPAddressField):
    def __init__(self, **kwargs):
        kwargs.setdefault('label', 'Endereço IP privado do equipamento')
        kwargs.setdefault('help_text', 'Aceita IP privado IPv4 ou IPv6, inclusive CGNAT. Ex.: 192.168.1.1 ou 10.20.30.1/24. A máscara é removida ao salvar.')
        kwargs.setdefault('widget', forms.TextInput(attrs={'placeholder':'192.168.1.1', 'autocomplete':'off', 'spellcheck':'false'}))
        super().__init__(**kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip()
            try:
                if '/' in value:
                    value = str(ipaddress.ip_interface(value).ip)
                address = ipaddress.ip_address(value)
                if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                    value = str(address.ipv4_mapped)
            except ValueError:
                raise forms.ValidationError('Informe um IP válido, como 192.168.1.1 ou 10.20.30.1/24.') from None
        return super().to_python(value)

    def validate(self, value):
        super().validate(value)
        if value and not allowed_management_ip(value):
            raise forms.ValidationError('Use um IP privado: 10.x.x.x, 172.16–31.x.x, 192.168.x.x, 100.64–127.x.x ou IPv6 fc00::/7.')
