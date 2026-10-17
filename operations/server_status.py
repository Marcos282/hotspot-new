import json
import shutil
from datetime import datetime,timezone
from pathlib import Path
from django.conf import settings


def wireguard_server_status(config):
    result={'active':False,'label':'Aguardando instalação','detail':'WireGuard não encontrado no servidor.'}
    if not shutil.which(settings.WG_EXECUTABLE):
        return result
    result.update(label='Sem confirmação',detail='Aguardando a verificação do serviço WireGuard.')
    try:
        snapshot=json.loads(Path(settings.WG_STATUS_FILE).read_text())
        if not isinstance(snapshot, dict):
            return result
        checked=datetime.fromisoformat(snapshot['checked_at'])
        result['checked_at'] = checked
        result['observed'] = {key: snapshot.get(key) for key in (
            'interface', 'addresses', 'port', 'service_state', 'service_substate',
            'enabled', 'started_at', 'mtu', 'interface_up', 'peer_count',
            'recent_peer_count', 'received_bytes', 'sent_bytes', 'last_handshake',
        )}
        age=(datetime.now(timezone.utc)-checked).total_seconds()
        if age<0 or age>180:
            result['detail']='A última verificação expirou.'
            return result
        if not config:
            result.update(label='Aguardando configuração',detail='Cadastre a interface e a chave pública do servidor na central.')
            return result
        matching=snapshot.get('interface')==config.interface and snapshot.get('public_key')==config.public_key and snapshot.get('port')==config.port and config.server_ip in snapshot.get('addresses',[])
        if not matching:
            result.update(label='Configuração divergente',detail='O estado observado não corresponde à configuração cadastrada.')
        elif snapshot.get('active') is True:
            result.update(active=True,label='Ativo',detail='Serviço e interface verificados. Conexões dos equipamentos são mostradas separadamente.')
        else:
            result.update(label='Inativo',detail='A interface ou o serviço WireGuard não está ativo.')
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        pass
    return result
