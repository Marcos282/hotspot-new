from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from tenants.db_context import tenant_database_context
from tenants.models import AccessSession, AuditEvent
from operations.models import NetworkConfiguration, HealthSample, ControlAuditEvent
from operations.management.commands.monitor_network import worker_user


class Command(BaseCommand):
    help = 'Mostra o expurgo por retenção configurada; exclui somente com --apply.'

    def add_arguments(self,parser):
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        user=worker_user()
        with tenant_database_context(None,user.pk,central=True):
            config=NetworkConfiguration.objects.filter(pk=1).first()
            if not config:
                self.stdout.write('Retenção não configurada; nenhum registro removido.')
                return
            plans=[]
            now=timezone.now()
            for model,days,timefield in [(AccessSession,config.session_retention_days,'ended_at'),(AuditEvent,config.audit_retention_days,'created_at'),(ControlAuditEvent,config.audit_retention_days,'created_at'),(HealthSample,config.monitoring_retention_days,'checked_at')]:
                if days:
                    query=model.objects.filter(**{timefield+'__lt':now-timedelta(days=days)})
                    count=query.count()
                    plans.append(f'{model._meta.model_name}: {count}')
                    if options['apply']:
                        query.delete()
            if options['apply']:
                ControlAuditEvent.objects.create(actor=user,action='executar expurgo configurado',fields_changed=['retention'])
            self.stdout.write(('Expurgo aplicado: ' if options['apply'] else 'Prévia: ') + ', '.join(plans))
