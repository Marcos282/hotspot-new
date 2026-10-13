import hashlib
import hmac
import ipaddress
import json
import socket
import ssl
import struct
import subprocess
import time
from operations.security import decrypt_secret


class RouterOSError(Exception):
    pass


def verify_route(ip, interface):
    address = ipaddress.ip_address(ip)
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise RouterOSError('Destino de gerência inválido.')
    try:
        result = subprocess.run(['/usr/sbin/ip', '-j', 'route', 'get', str(address)], capture_output=True, text=True, timeout=5, check=True)
        routes = json.loads(result.stdout)
        if not routes or routes[0].get('dev') != interface:
            raise RouterOSError('A API não está roteada pela interface VPN autorizada.')
    except (OSError, subprocess.SubprocessError, ValueError):
        raise RouterOSError('Não foi possível confirmar a rota VPN da API.') from None


def encode_length(length):
    if length < 0x80:
        return bytes([length])
    if length < 0x4000:
        return struct.pack('>H', length | 0x8000)
    if length < 0x200000:
        return (length | 0xC00000).to_bytes(3, 'big')
    if length < 0x10000000:
        return struct.pack('>I', length | 0xE0000000)
    return b'\xf0' + struct.pack('>I', length)


class RouterOSClient:
    ALLOWED_COMMANDS = {'/system/resource/print', '/ip/hotspot/print', '/ip/hotspot/active/print'}

    def __init__(self, device, interface):
        self.device = device
        self.interface = interface
        self.socket = None
        self.total_bytes = 0
        self.deadline = 0

    def __enter__(self):
        verify_route(self.device.management_ip, self.interface)
        if not self.device.api_username or not self.device.api_password_encrypted:
            raise RouterOSError('Credenciais API-SSL ainda não configuradas.')
        raw = None
        try:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            if self.device.certificate_sha256:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            raw = socket.create_connection((self.device.management_ip, 8729), timeout=5)
            self.socket = context.wrap_socket(raw, server_hostname=self.device.management_ip)
            if self.device.certificate_sha256:
                digest = hashlib.sha256(self.socket.getpeercert(binary_form=True)).hexdigest()
                if not hmac.compare_digest(digest, self.device.certificate_sha256.lower()):
                    raise RouterOSError('Certificado API-SSL diferente do fingerprint cadastrado.')
            password = decrypt_secret(self.device.api_password_encrypted)
            self._command(['/login', '=name=' + self.device.api_username, '=password=' + password])
            return self
        except Exception:
            if self.socket:
                self.socket.close()
            elif raw:
                raw.close()
            raise

    def __exit__(self, *args):
        if self.socket:
            self.socket.close()

    def _read(self, size):
        if size > 1024 * 1024 or self.total_bytes + size > 8 * 1024 * 1024:
            raise RouterOSError('Resposta API acima do limite de segurança.')
        self.total_bytes += size
        value = b''
        while len(value) < size:
            if time.monotonic() > self.deadline:
                raise RouterOSError('Tempo máximo da resposta API excedido.')
            chunk = self.socket.recv(size-len(value))
            if not chunk:
                raise RouterOSError('Conexão API encerrada.')
            value += chunk
        return value

    def _word(self):
        first = self._read(1)[0]
        if first < 0x80:
            length = first
        elif first < 0xC0:
            length = ((first & 0x3F) << 8) | self._read(1)[0]
        elif first < 0xE0:
            length = ((first & 0x1F) << 16) | int.from_bytes(self._read(2), 'big')
        elif first < 0xF0:
            length = ((first & 0x0F) << 24) | int.from_bytes(self._read(3), 'big')
        elif first == 0xF0:
            length = int.from_bytes(self._read(4), 'big')
        else:
            raise RouterOSError('Controle API desconhecido.')
        return self._read(length).decode('utf-8', errors='replace') if length else ''

    def _command(self, words):
        self.total_bytes = 0
        self.deadline = time.monotonic() + 15
        payload = b''
        for word in words:
            value = word.encode()
            payload += encode_length(len(value)) + value
        self.socket.sendall(payload + b'\0')
        records = []
        while True:
            sentence = []
            while True:
                word = self._word()
                if not word:
                    break
                sentence.append(word)
                if len(sentence) > 200:
                    raise RouterOSError('Sentença API inválida.')
            if not sentence:
                continue
            if sentence[0] in ['!trap', '!fatal']:
                # Never return router-supplied error details: they can contain secrets.
                raise RouterOSError('Comando API recusado pelo equipamento.')
            if sentence[0] == '!done':
                return records
            if sentence[0] == '!re':
                record = {}
                for item in sentence[1:]:
                    if item.startswith('=') and '=' in item[1:]:
                        key, value = item[1:].split('=',1)
                        record[key] = value
                records.append(record)
                if len(records) > 10000:
                    raise RouterOSError('Quantidade de registros API acima do limite.')

    def read(self, command, properties):
        if command not in self.ALLOWED_COMMANDS:
            raise RouterOSError('Este adaptador permite somente comandos de consulta.')
        return self._command([command, '=.proplist=' + ','.join(properties)])
