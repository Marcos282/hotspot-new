from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from cryptography.fernet import Fernet, InvalidToken


def cipher():
    if not settings.ROUTEROS_CREDENTIAL_KEY:
        raise ImproperlyConfigured('Configure ROUTEROS_CREDENTIAL_KEY fora do banco de dados.')
    try:
        return Fernet(settings.ROUTEROS_CREDENTIAL_KEY.encode())
    except (ValueError, TypeError):
        raise ImproperlyConfigured('ROUTEROS_CREDENTIAL_KEY inválida.') from None


def encrypt_secret(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt_secret(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise ImproperlyConfigured('Não foi possível abrir a credencial; verifique a chave de criptografia.') from None
