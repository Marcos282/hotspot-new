import ipaddress
import struct
import zlib
from django import forms
from tenants.models import Device, AccessPlan, HotspotConfiguration


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ['name', 'management_ip', 'routeros_version', 'enabled']

    def clean_management_ip(self):
        value = self.cleaned_data['management_ip']
        ip = ipaddress.ip_address(value)
        networks = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7']
        if not any(ip in ipaddress.ip_network(network) for network in networks):
            raise forms.ValidationError('Informe um IP privado da rede ou VPN.')
        return value


from tenants.panel_forms import PriceField


class AccessPlanForm(forms.ModelForm):
    price = PriceField()
    speed_limit = forms.CharField(label='Limite de velocidade', required=False, max_length=32, help_text='Opcional. Exemplo: 5M/10M. Aplicado ao criar um acesso no MikroTik.')
    duration_minutes = forms.TypedChoiceField(label='Duração do acesso', coerce=int, choices=[(60,'1 hora'),(180,'3 horas'),(360,'6 horas')])
    class Meta:
        model = AccessPlan
        fields = ['name', 'duration_minutes', 'price', 'speed_limit', 'enabled']

    def clean_speed_limit(self):
        import re
        value = self.cleaned_data['speed_limit']
        if value and not re.fullmatch(r'[1-9][0-9]*[kM]?/[1-9][0-9]*[kM]?', value):
            raise forms.ValidationError('Use um limite como 5M/10M.')
        return value


class HotspotForm(forms.ModelForm):
    class Meta:
        model = HotspotConfiguration
        fields = ['title', 'welcome_text', 'free_access']


class BrandImageForm(forms.Form):
    kind = forms.ChoiceField(label='Tipo', choices=[('logo', 'Logotipo'), ('advertisement', 'Publicidade')])
    title = forms.CharField(label='Descrição', max_length=120)
    image = forms.FileField(label='Imagem PNG (até 2 MB)')

    def clean_image(self):
        upload = self.cleaned_data['image']
        if upload.size > 2 * 1024 * 1024:
            raise forms.ValidationError('A imagem deve ter no máximo 2 MB.')
        data = upload.read()
        try:
            if data[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError()
            pos = 8
            chunks = []
            payload = b''
            width = height = 0
            while pos < len(data):
                length = struct.unpack('>I', data[pos:pos+4])[0]
                kind = data[pos+4:pos+8]
                body = data[pos+8:pos+8+length]
                crc = struct.unpack('>I', data[pos+8+length:pos+12+length])[0]
                if crc != zlib.crc32(kind + body) & 0xffffffff:
                    raise ValueError()
                if kind == b'IHDR':
                    if chunks or length != 13:
                        raise ValueError()
                    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', body)
                    if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= 4000000 and depth == 8 and color in [2, 6] and compression == filtering == interlace == 0):
                        raise ValueError()
                elif kind == b'IDAT':
                    payload += body
                elif kind != b'IEND':
                    # Strip ancillary metadata; reject unknown critical chunks.
                    if not kind[0] & 32:
                        raise ValueError()
                    pos += 12 + length
                    continue
                chunks.append(data[pos:pos+12+length])
                pos += 12 + length
                if kind == b'IEND':
                    if length or pos != len(data):
                        raise ValueError()
                    break
            if not chunks or chunks[-1][4:8] != b'IEND' or not width:
                raise ValueError()
            expected = height * (1 + width * (3 if color == 2 else 4))
            decoder = zlib.decompressobj()
            pixels = decoder.decompress(payload, expected + 1)
            if len(pixels) != expected or not decoder.eof or decoder.unused_data:
                raise ValueError()
            row_size = expected // height
            if any(pixels[i * row_size] > 4 for i in range(height)):
                raise ValueError()
            return data[:8] + b''.join(chunks)
        except (ValueError, struct.error, zlib.error, IndexError):
            raise forms.ValidationError('Envie um PNG RGB ou RGBA válido, sem entrelaçamento, com até 4 milhões de pixels.')
