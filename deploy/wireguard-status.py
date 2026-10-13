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
    links=json.loads(read('/usr/sbin/ip','-j','link','show','dev','wg0'))
    addresses=json.loads(read('/usr/sbin/ip','-j','address','show','dev','wg0'))
    status.update(public_key=read('/usr/bin/wg','show','wg0','public-key'),port=int(read('/usr/bin/wg','show','wg0','listen-port')),addresses=[item['local'] for row in addresses for item in row.get('addr_info',[])])
    status['active']=bool(links and 'UP' in links[0]['flags'] and read('/usr/bin/systemctl','is-active','wg-quick@wg0')=='active')
except (RuntimeError,OSError,ValueError,subprocess.SubprocessError):
    status['detail']='Serviço ou interface indisponível'
root=Path('/var/lib/novainfo')
root.mkdir(mode=0o755,exist_ok=True)
temporary=root/'wireguard-status.tmp'
with temporary.open('w') as output:
    json.dump(status,output)
os.chmod(temporary,0o644)
temporary.replace(root/'wireguard-status.json')
