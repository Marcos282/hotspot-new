from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ImproperlyConfigured
from tenants.db_context import tenant_database_context
from operations.management.commands.monitor_network import worker_user
from operations.billing import reconcile_subscription
from operations.mercadopago import PaymentIntegrationError
from operations.models import SaaSSubscription


class Command(BaseCommand):
    help='Consulta no Mercado Pago uma assinatura pelo ID, inclusive após notificação não entregue.'

    def add_arguments(self,parser):
        parser.add_argument('provider_id')

    def handle(self,*args,**options):
        worker=worker_user()
        try:
            with tenant_database_context(None,worker.pk,central=True):
                subscription=reconcile_subscription(options['provider_id'],worker)
                label=subscription.get_status_display()
        except (ImproperlyConfigured,PaymentIntegrationError,SaaSSubscription.DoesNotExist,ValueError) as error:
            raise CommandError('Não foi possível validar a assinatura; revise identificação e configuração.') from None
        self.stdout.write(label+' (não confirma pagamento de parcela).')
