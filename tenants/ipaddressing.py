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


class ManagementIPField(forms.GenericIPAddressField):
    def __init__(self, **kwargs):
        kwargs.setdefault('label', 'Endereço IP do equipamento')
        kwargs.setdefault('help_text', 'Aceita qualquer IPv4 ou IPv6 válido, público ou privado. Você também pode informar a máscara, como 192.168.1.1/24; somente o IP será salvo.')
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
