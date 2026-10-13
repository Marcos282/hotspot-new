from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ImproperlyConfigured
from tenants.db_context import tenant_database_context
from tenants.models import AuditEvent
from operations.models import SaaSSubscription
from operations.billing import create_remote_subscription,subscription_credentials
from operations.mercadopago import PaymentIntegrationError
from operations.management.commands.monitor_network import worker_user


class Command(BaseCommand):
    help='Processa solicitações de assinatura mensal que os estabelecimentos autorizaram pelo painel.'

    def handle(self,*args,**options):
        worker=worker_user()
        try:
            subscription_credentials()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from None
        count=0
        while True:
            # Commit durable intent BEFORE an external request. Ambiguous failures are not retried.
            with tenant_database_context(None,worker.pk,central=True):
                subscription=SaaSSubscription.objects.select_for_update().filter(status='requested').select_related('plan','tenant').first()
                if subscription is None:
                    break
                subscription.status='creating'
                subscription.save(update_fields=['status','updated_at'])
            try:
                reference,checkout=create_remote_subscription(subscription)
            except (ImproperlyConfigured,PaymentIntegrationError,ValueError):
                with tenant_database_context(None,worker.pk,central=True):
                    SaaSSubscription.objects.filter(pk=subscription.pk,status='creating').update(status='error')
                self.stderr.write('Solicitação exige revisão na conta Mercado Pago; nenhuma repetição automática realizada.')
                continue
            with tenant_database_context(None,worker.pk,central=True):
                current=SaaSSubscription.objects.select_for_update().get(pk=subscription.pk)
                # A webhook may have confirmed authorization before the worker saved the checkout.
                current.provider_reference=reference
                current.checkout_url=checkout
                if current.status=='creating':
                    current.status='pending'
                current.save(update_fields=['provider_reference','checkout_url','status','updated_at'])
                AuditEvent.objects.create(tenant=current.tenant,actor=worker,action='criar checkout mensal SaaS',object_type='saassubscription',object_id=current.pk,fields_changed=['provider_reference','checkout_url','status'])
            count+=1
        self.stdout.write(f'{count} checkouts de assinatura preparados. Autorizar recorrência não confirma o pagamento de uma parcela.')
