import ipaddress
import re
import subprocess
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from operations.models import NetworkConfiguration, WireGuardPeer


class WireGuardError(Exception):
    pass


def command(*arguments):
    try:
        result = subprocess.run([settings.WG_EXECUTABLE, *arguments], capture_output=True, text=True, timeout=10, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise WireGuardError('WireGuard indisponível ou sem permissão no servidor.') from None


def snapshot(interface):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', interface):
        raise WireGuardError('Interface inválida.')
    handshakes = {}
    routes = {}
    try:
        for line in command('show', interface, 'latest-handshakes').splitlines():
            key, stamp = line.split()
            handshakes[key] = int(stamp)
        for line in command('show', interface, 'allowed-ips').splitlines():
            key, addresses = line.split('\t', 1)
            routes[key] = [ipaddress.ip_network(item.strip()) for item in addresses.split(',')]
    except (ValueError, TypeError):
        raise WireGuardError('Resposta WireGuard inválida.') from None
    return handshakes, routes


@transaction.atomic
def allocate_peer(device, public_key, requested_ip=None):
    config = NetworkConfiguration.objects.select_for_update().get(pk=1)
    if WireGuardPeer.objects.filter(device=device).exists():
        raise ValidationError('Este equipamento já possui um peer. Revise o cadastro existente.')
    network = ipaddress.ip_network(config.network)
    taken = set(WireGuardPeer.objects.values_list('vpn_ip', flat=True)) | {config.server_ip}
    if requested_ip:
        address = ipaddress.ip_address(requested_ip)
        if address not in network or address in (network.network_address, network.broadcast_address) or str(address) in taken:
            raise ValidationError('IP fora da rede VPN ou já reservado.')
    else:
        address = next((ip for ip in network.hosts() if str(ip) not in taken), None)
        if address is None:
            raise ValidationError('Não há IP livre na rede VPN.')
    peer = WireGuardPeer(tenant=device.tenant, device=device, public_key=public_key, vpn_ip=str(address))
    peer.full_clean()
    peer.save()
    return peer


def expected_routes(peer):
    # This release reserves exactly one management /32 per peer.
    return [ipaddress.ip_network(f'{peer.vpn_ip}/32')]


def server_configuration(peer):
    return f'# Revisar antes de aplicar. Somente o peer selecionado.\n[Peer]\nPublicKey = {peer.public_key}\nAllowedIPs = {peer.vpn_ip}/32\n'


def client_configuration(peer, config):
    return f'''# Modelo para gateway WireGuard. A chave privada nunca é armazenada na Nova Info.
# Preencha localmente; revise antes de aplicar.
[Interface]
PrivateKey = PREENCHA_LOCALMENTE
Address = {peer.vpn_ip}/32

[Peer]
PublicKey = {config.public_key}
AllowedIPs = {config.server_ip}/32
Endpoint = {config.endpoint}:{config.port}
PersistentKeepalive = 25
'''


def routeros_script(peer, config):
    version = peer.device.routeros_version
    if not re.fullmatch(r'[67]\.[0-9]+(?:\.[0-9]+)?(?:[a-zA-Z0-9.-]*)?', version):
        raise ValidationError('Informe a versão RouterOS 6 ou 7 antes de gerar o script.')
    if version.startswith('6.'):
        return '''# RouterOS 6 não oferece WireGuard nativo.
# Atualize para RouterOS 7 ou use gateway WireGuard externo revisado.
# O gateway deverá encaminhar a gerência via VPN; esta versão de monitoramento
# requer que o IP de gerência roteado seja igual ao /32 reservado do peer.
# Nenhuma configuração existente será alterada por este arquivo.
:put "WireGuard nativo indisponível: aguardando gateway compatível ou atualização."
'''
    name = f'ni-wg-{peer.device_id}'
    # Stop before any mutation if existing objects would be reused or overwritten.
    return f'''# REVISÃO OBRIGATÓRIA. Somente RouterOS 7. Não aplicar automaticamente.
# Primeiro crie uma interface dedicada {name} e cadastre sua chave pública na Nova Info.
# Não use o endpoint público do MikroTik para API. API-SSL somente pela VPN.
:local iface [/interface wireguard find where name="{name}"]
:if ([:len $iface] != 1) do={{ :error "Crie/revise a interface dedicada antes de continuar" }}
:if ([/interface wireguard get $iface public-key] != "{peer.public_key}") do={{ :error "Chave pública diferente do peer cadastrado" }}
:if ([:len [/interface wireguard peers find where interface=$iface]] > 0) do={{ :error "Interface já possui peers; revisão manual necessária" }}
:if ([:len [/ip address find where interface="{name}"]] > 0) do={{ :error "Interface já possui endereços; revisão manual necessária" }}
/interface wireguard peers add interface="{name}" public-key="{config.public_key}" endpoint-address="{config.endpoint}" endpoint-port={config.port} allowed-address={config.server_ip}/32 persistent-keepalive=25s comment="Nova Info peer {peer.pk}"
/ip address add address={peer.vpn_ip}/32 network={config.server_ip} interface="{name}" comment="Nova Info gerenciamento"
# Revise regras input/forward existentes antes de liberar tráfego.
# API-SSL: certificado válido ou fingerprint confirmado, usuário com policy=read,api.
# Limite a origem da API ao IP VPN {config.server_ip}; não exponha 8728/8729 na WAN.
# Alterações de /ip service e firewall ficam para revisão separada, sem sobrescrita automática.
'''


def apply_peer(peer):
    config = NetworkConfiguration.objects.get(pk=1)
    handshakes, routes = snapshot(config.interface)
    if not peer.enabled:
        if peer.public_key in routes or peer.public_key in handshakes:
            command('set', config.interface, 'peer', peer.public_key, 'remove')
        _, current_routes = snapshot(config.interface)
        if peer.public_key in current_routes:
            raise WireGuardError('A remoção ainda não foi confirmada no servidor.')
        peer.removal_confirmed_at = timezone.now()
        peer.save(update_fields=['removal_confirmed_at'])
        return 'Remoção confirmada. Atualize também a configuração persistente do servidor.'
    desired = expected_routes(peer)
    if peer.public_key in routes:
        if routes[peer.public_key] != desired:
            raise WireGuardError('Peer existente possui rotas diferentes. Nenhuma sobrescrita realizada.')
        return 'Peer já está configurado com a rota esperada.'
    for key, networks in routes.items():
        if any(left.overlaps(right) for left in networks for right in desired):
            raise WireGuardError('O IP se sobrepõe a um peer existente. Nenhuma alteração realizada.')
    command('set', config.interface, 'peer', peer.public_key, 'allowed-ips', str(desired[0]))
    return 'Peer aplicado em runtime. Revise e atualize a configuração persistente antes de reiniciar.'
