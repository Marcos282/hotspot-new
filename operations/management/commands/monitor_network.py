from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from tenants.db_context import tenant_database_context
from operations.monitoring import poll_all


def worker_user():
    try:
        user = get_user_model().objects.get(pk=int(settings.WG_MONITOR_USER_ID), is_active=True, is_staff=True)
    except (ValueError,TypeError,get_user_model().DoesNotExist):
        raise CommandError('Configure WG_MONITOR_USER_ID com uma conta de serviço autorizada.') from None
    if not user.has_perm('operations.manage_network'):
        raise CommandError('A conta de serviço não possui operations.manage_network.')
    return user


class Command(BaseCommand):
    help = 'Uma rodada de monitoramento real. Agende externamente a cada 60 segundos.'

    def handle(self,*args,**options):
        user=worker_user()
        with tenant_database_context(None,user.pk,central=True):
            count=poll_all()
        self.stdout.write(f'{count} equipamentos verificados. Sem configuração central, nenhum equipamento é consultado.')
