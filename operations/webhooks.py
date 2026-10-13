from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from tenants.db_context import tenant_database_context
from operations.management.commands.monitor_network import worker_user
from operations.mercadopago import verify_webhook, PaymentIntegrationError
from operations.billing import subscription_credentials, reconcile_subscription
from operations.models import SaaSSubscription


@csrf_exempt
@require_POST
def subscription_webhook(request):
    provider_id=request.GET.get('data.id','')
    try:
        token,secret,collector=subscription_credentials()
    except ImproperlyConfigured:
        return HttpResponse('Assinaturas não configuradas.',status=503)
    if not verify_webhook(provider_id,request.headers.get('X-Request-Id',''),request.headers.get('X-Signature',''),secret):
        return HttpResponse(status=401)
    try:
        worker=worker_user()
        with tenant_database_context(None,worker.pk,central=True):
            reconcile_subscription(provider_id,worker)
    except (ImproperlyConfigured,CommandError,PaymentIntegrationError,SaaSSubscription.DoesNotExist):
        return HttpResponse('Não foi possível confirmar a assinatura.',status=503)
    return HttpResponse(status=200)
