"""Send transactional email through Resend SMTP over SSL."""
import logging
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend
from django.core.exceptions import ImproperlyConfigured


logger = logging.getLogger(__name__)


class EmailBackend(SMTPEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        if not self.password or not settings.DEFAULT_FROM_EMAIL:
            if self.fail_silently:
                return 0
            raise ImproperlyConfigured('Configure EMAIL_HOST_PASSWORD e DEFAULT_FROM_EMAIL (ou RESEND_API_KEY e RESEND_FROM_EMAIL).')
        try:
            return super().send_messages(email_messages)
        except Exception as error:
            # Do not log SMTP response bodies, credentials or recipient addresses.
            code = getattr(error, 'smtp_code', None)
            logger.error('Falha no SMTP Resend: tipo=%s codigo=%s', type(error).__name__, code)
            if self.fail_silently:
                return 0
            raise RuntimeError('Não foi possível enviar o e-mail pelo SMTP do Resend.') from None
