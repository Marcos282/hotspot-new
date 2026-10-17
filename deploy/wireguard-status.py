#!/usr/bin/python3
import datetime
import json
import os
from pathlib import Path
import subprocess


def read(*args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=5)
    if result.returncode:
        raise RuntimeError('Unavailable')
    return result.stdout.strip()


status={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'interface':'wg0','active':False}
try:
    properties = dict(line.split('=', 1) for line in read(
        '/usr/bin/systemctl', 'show', 'wg-quick@wg0',
        '--property=ActiveState,SubState,UnitFileState,ActiveEnterTimestamp'
    ).splitlines() if '=' in line)
    status.update(service_state=properties.get('ActiveState'),
                  service_substate=properties.get('SubState'),
                  enabled=properties.get('UnitFileState'),
                  started_at=properties.get('ActiveEnterTimestamp'))
    links=json.loads(read('/usr/sbin/ip','-j','link','show','dev','wg0'))
    addresses=json.loads(read('/usr/sbin/ip','-j','address','show','dev','wg0'))
    status.update(public_key=read('/usr/bin/wg','show','wg0','public-key'),port=int(read('/usr/bin/wg','show','wg0','listen-port')),addresses=[item['local'] for row in addresses for item in row.get('addr_info',[])])
    status.update(mtu=links[0].get('mtu') if links else None,
                  interface_up=bool(links and 'UP' in links[0]['flags']))
    status['active']=bool(links and 'UP' in links[0]['flags'] and read('/usr/bin/systemctl','is-active','wg-quick@wg0')=='active')
    handshakes = [int(line.split()[1]) for line in read('/usr/bin/wg', 'show', 'wg0', 'latest-handshakes').splitlines()]
    transfers = [tuple(map(int, line.split()[1:])) for line in read('/usr/bin/wg', 'show', 'wg0', 'transfer').splitlines()]
    now = datetime.datetime.now(datetime.timezone.utc)
    latest = max(handshakes, default=0)
    status.update(peer_count=len(handshakes),
                  recent_peer_count=sum(0 <= now.timestamp() - stamp <= 180 for stamp in handshakes if stamp > 0),
                  last_handshake=datetime.datetime.fromtimestamp(latest, datetime.timezone.utc).isoformat() if latest else None,
                  received_bytes=sum(row[0] for row in transfers),
                  sent_bytes=sum(row[1] for row in transfers))
except (RuntimeError,OSError,ValueError,IndexError,KeyError,subprocess.SubprocessError):
    status['detail']='Serviço ou interface indisponível'
root=Path('/var/lib/novainfo')
root.mkdir(mode=0o755,exist_ok=True)
temporary=root/'wireguard-status.tmp'
with temporary.open('w') as output:
    json.dump(status,output)
os.chmod(temporary,0o644)
temporary.replace(root/'wireguard-status.json')
