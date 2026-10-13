"""Django email backend using the Resend HTTPS API."""
import json
from urllib.request import Request, urlopen
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.exceptions import ImproperlyConfigured


class EmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not settings.RESEND_API_KEY or not settings.DEFAULT_FROM_EMAIL:
            raise ImproperlyConfigured('Configure RESEND_API_KEY e RESEND_FROM_EMAIL.')
        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            payload = {'from': message.from_email, 'to': message.to,
                       'subject': message.subject, 'text': message.body}
            if message.cc:
                payload['cc'] = message.cc
            if message.bcc:
                payload['bcc'] = message.bcc
            request = Request('https://api.resend.com/emails',
                              data=json.dumps(payload).encode(), method='POST',
                              headers={'Authorization': f'Bearer {settings.RESEND_API_KEY}',
                                       'Content-Type': 'application/json',
                                       'User-Agent': 'NovaInfo/1.0'})
            try:
                with urlopen(request, timeout=15) as response:
                    result = json.load(response)
                if not result.get('id'):
                    raise ValueError('Missing delivery ID')
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise RuntimeError('Não foi possível enviar o e-mail pelo Resend.') from None
        return sent
