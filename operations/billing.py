import os
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from operations.models import SaaSSubscription
from operations.mercadopago import api_request, PaymentIntegrationError
from tenants.models import AuditEvent


def subscription_credentials():
    token=os.environ.get('MERCADOPAGO_ACCESS_TOKEN','')
    secret=os.environ.get('MERCADOPAGO_WEBHOOK_SECRET','')
    collector=os.environ.get('MERCADOPAGO_COLLECTOR_ID','')
    if os.environ.get('MERCADOPAGO_SUBSCRIPTIONS_ENABLED','false').lower()!='true' or not token or not secret or not collector.isdigit():
        raise ImproperlyConfigured('Configure e homologue a assinatura mensal Mercado Pago antes de ativar a cobrança.')
    return token,secret,collector


def valid_checkout_url(value):
    try:
        parsed=urlsplit(value)
        port=parsed.port
    except ValueError:
        return False
    return parsed.scheme=='https' and parsed.hostname in ['www.mercadopago.com.br','www.mercadopago.com','www.mercadopago.com.ar'] and not parsed.username and not parsed.password and port in [None,443]


def create_remote_subscription(subscription):
    token,secret,collector=subscription_credentials()
    root=os.environ.get('NOVAINFO_PUBLIC_URL','https://novainfo.com.br').rstrip('/')
    parsed=urlsplit(root)
    if parsed.scheme!='https' or parsed.hostname!='novainfo.com.br' or parsed.path:
        raise ImproperlyConfigured('NOVAINFO_PUBLIC_URL deve ser https://novainfo.com.br para o checkout de produção.')
    response=api_request('POST','/preapproval',token,payload={
        'reason':'Nova Info — '+subscription.plan.name[:80],
        'external_reference':'ni-sub:'+str(subscription.external_id),
        'payer_email':subscription.payer_email,
        'auto_recurring':{'frequency':1,'frequency_type':'months','transaction_amount':float(subscription.monthly_amount),'currency_id':'BRL'},
        'back_url':root+'/minha-conta/',
        'notification_url':root+'/integracoes/mercado-pago/assinaturas/webhook/',
        'status':'pending',
    },idempotency_key=str(subscription.external_id))
    reference=str(response.get('id',''))
    checkout=str(response.get('init_point',''))
    if not re.fullmatch('[A-Za-z0-9-]{1,64}',reference) or not valid_checkout_url(checkout):
        raise PaymentIntegrationError('Resposta de assinatura inválida. Revise a conta Mercado Pago antes de repetir.')
    if str(response.get('collector_id'))!=collector or response.get('external_reference')!='ni-sub:'+str(subscription.external_id):
        raise PaymentIntegrationError('A assinatura não corresponde ao recebedor ou à solicitação.')
    return reference,checkout


def reconcile_subscription(provider_id,actor):
    token,secret,collector=subscription_credentials()
    if not re.fullmatch('[A-Za-z0-9-]{1,64}',provider_id):
        raise PaymentIntegrationError('ID de assinatura inválido.')
    response=api_request('GET','/preapproval/'+provider_id,token)
    reference=str(response.get('external_reference',''))
    if not re.fullmatch('ni-sub:[0-9a-f-]{36}',reference) or str(response.get('id'))!=provider_id or str(response.get('collector_id'))!=collector:
        raise PaymentIntegrationError('A assinatura não pertence à Nova Info ou à solicitação esperada.')
    recurring=response.get('auto_recurring',{})
    try:
        amount=Decimal(str(recurring.get('transaction_amount','')))
    except InvalidOperation:
        raise PaymentIntegrationError('Valor de assinatura inválido.') from None
    if not amount.is_finite() or recurring.get('currency_id')!='BRL' or recurring.get('frequency')!=1 or recurring.get('frequency_type')!='months':
        raise PaymentIntegrationError('A periodicidade ou moeda não corresponde à assinatura mensal.')
    status=response.get('status','')
    if status not in ['pending','authorized','paused','cancelled']:
        raise PaymentIntegrationError('Status de autorização de assinatura desconhecido.')
    with transaction.atomic():
        subscription=SaaSSubscription.objects.select_for_update().get(external_id=reference[7:])
        if amount!=subscription.monthly_amount or (subscription.provider_reference and subscription.provider_reference!=provider_id):
            raise PaymentIntegrationError('Valor ou identificação da assinatura difere do registro.')
        changed=subscription.status!=status or not subscription.provider_reference
        subscription.status=status
        subscription.provider_reference=provider_id
        subscription.save(update_fields=['status','provider_reference','updated_at'])
        if changed:
            AuditEvent.objects.create(tenant=subscription.tenant,actor=actor,action='reconciliar assinatura SaaS',object_type='saassubscription',object_id=subscription.pk,fields_changed=['status','provider_reference'])
    return subscription
