#!/bin/bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
    echo 'Execute este script com sudo no seu terminal.' >&2
    exit 1
fi
PROJECT=/var/www/html/novainfo/servidormk
CONFIG=/etc/wireguard/wg0.conf
for existing in /etc/systemd/system/novainfo-wireguard-status.service /etc/systemd/system/novainfo-wireguard-status.timer /usr/local/libexec/novainfo-wireguard-status; do
    if [[ -e "$existing" ]]; then
        echo 'Um componente da instalação já existe; revisão necessária, sem sobrescrita automática.' >&2
        exit 1
    fi
done
if [[ -e "$CONFIG" ]]; then
    echo 'wg0.conf já existe. Nenhuma configuração será sobrescrita; revisão manual necessária.' >&2
    exit 1
fi
if ip link show wg0 >/dev/null 2>&1; then
    echo 'A interface wg0 já existe; nenhuma alteração será realizada.' >&2
    exit 1
fi
python3 - <<'PY'
import ipaddress,json,subprocess
network=ipaddress.ip_network('10.77.0.0/24')
routes=json.loads(subprocess.check_output(['/usr/sbin/ip','-j','route','show'],text=True))
for route in routes:
    dest=route.get('dst','default')
    if dest!='default' and ipaddress.ip_network(dest,strict=False).overlaps(network):
        raise SystemExit('A rede 10.77.0.0/24 se sobrepõe a uma rota existente. Revisão necessária.')
PY
apt-get update
apt-get install -y wireguard-tools
install -d -m 700 /etc/wireguard
umask 077
python3 - <<'PY'
from pathlib import Path
import subprocess,os
key=subprocess.check_output(['/usr/bin/wg','genkey'],text=True).strip()
path=Path('/etc/wireguard/wg0.conf')
with path.open('x') as output:
    output.write('[Interface]\nAddress = 10.77.0.1/24\nListenPort = 51820\nPrivateKey = '+key+'\n')
os.chmod(path,0o600)
PY
systemctl enable --now wg-quick@wg0
install -D -o root -g root -m 755 "$PROJECT/deploy/wireguard-status.py" /usr/local/libexec/novainfo-wireguard-status
cat > /etc/systemd/system/novainfo-wireguard-status.service <<'EOF'
[Unit]
Description=Nova Info - estado publico do servidor WireGuard
After=wg-quick@wg0.service

[Service]
Type=oneshot
ExecStart=/usr/local/libexec/novainfo-wireguard-status
UMask=0022
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/novainfo
NoNewPrivileges=true
CapabilityBoundingSet=CAP_NET_ADMIN
EOF
cat > /etc/systemd/system/novainfo-wireguard-status.timer <<'EOF'
[Unit]
Description=Atualizar estado WireGuard no painel Nova Info

[Timer]
OnBootSec=5
OnUnitInactiveSec=60
AccuracySec=5
Unit=novainfo-wireguard-status.service

[Install]
WantedBy=timers.target
EOF
install -d -o root -g root -m 755 /var/lib/novainfo
systemctl daemon-reload
systemctl enable --now novainfo-wireguard-status.timer
systemctl start novainfo-wireguard-status.service
cd "$PROJECT"
WG_SETUP_ENDPOINT="${1:-192.168.6.132}" "$PROJECT/myenv/bin/python" - <<'PY'
import os,subprocess
os.environ.setdefault('DJANGO_SETTINGS_MODULE','novainfo.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from tenants.db_context import tenant_database_context
from operations.models import NetworkConfiguration,ControlAuditEvent
user=get_user_model().objects.filter(is_active=True,is_superuser=True).first()
if not user:
    raise SystemExit('WireGuard iniciado. Crie um administrador e cadastre a configuração no painel.')
key=subprocess.check_output(['/usr/bin/wg','show','wg0','public-key'],text=True).strip()
with tenant_database_context(None,user.pk,central=True):
    if NetworkConfiguration.objects.exists():
        raise SystemExit('WireGuard iniciado. A configuração do painel já existe e não foi sobrescrita; revise a chave pública e a interface.')
    config=NetworkConfiguration(endpoint=os.environ['WG_SETUP_ENDPOINT'],public_key=key,interface='wg0',network='10.77.0.0/24',server_ip='10.77.0.1',port=51820)
    config.full_clean()
    config.save()
    ControlAuditEvent.objects.create(actor=None,action='instalar servidor WireGuard pelo administrador do sistema',fields_changed=['interface','network','server_ip','public_key','port','endpoint'])
print('WireGuard iniciado. Configuração registrada no painel; endpoint inicial de rede local.')
PY
systemctl is-active wg-quick@wg0
printf '%s\n' 'Concluído. O painel verifica o estado real do servidor. Ainda não há peers conectados.'
