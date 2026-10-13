import hashlib
import hmac
import json
import os
import re
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError
from django.core.exceptions import ImproperlyConfigured


class PaymentIntegrationError(Exception):
    pass


def verify_webhook(data_id,request_id,signature,secret,now=None):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,64}',str(data_id)) or not request_id or len(request_id)>200:
        return False
    try:
        parts=dict(item.strip().split('=',1) for item in signature.split(','))
        ts=parts['ts']
        digest=parts['v1']
        if not ts.isdigit() or not re.fullmatch('[0-9a-f]{64}',digest):
            return False
        timestamp=int(ts)
        seconds=timestamp/1000 if timestamp>10**12 else timestamp
        if abs((now if now is not None else time.time())-seconds)>300:
            return False
        manifest=f'id:{str(data_id).lower()};request-id:{request_id};ts:{ts};'
        expected=hmac.new(secret.encode(),manifest.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,digest)
    except (ValueError,KeyError,TypeError):
        return False


def api_request(method,path,token,payload=None,idempotency_key=None):
    if not re.fullmatch(r'/preapproval(?:/[A-Za-z0-9-]{1,64})?',path):
        raise PaymentIntegrationError('Rota financeira não autorizada.')
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    if idempotency_key:
        headers['X-Idempotency-Key']=idempotency_key
    body=json.dumps(payload).encode() if payload is not None else None
    request=Request('https://api.mercadopago.com'+path,data=body,headers=headers,method=method)
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            return None
    try:
        with build_opener(NoRedirect()).open(request,timeout=8) as response:
            content=response.read(1024*1024+1)
            if len(content)>1024*1024:
                raise PaymentIntegrationError('Resposta financeira acima do limite.')
            return json.loads(content)
    except (URLError,ValueError,OSError):
        raise PaymentIntegrationError('Mercado Pago indisponível ou credencial recusada.') from None

