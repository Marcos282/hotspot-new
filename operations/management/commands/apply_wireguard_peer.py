from django.core.management.base import BaseCommand, CommandError
from tenants.db_context import tenant_database_context
from tenants.models import AuditEvent
from operations.models import WireGuardPeer
from operations.wireguard import apply_peer, WireGuardError
from operations.management.commands.monitor_network import worker_user


class Command(BaseCommand):
    help = 'Aplica ou remove somente um peer após revisão explícita. Não sobrescreve wg0.conf.'

    def add_arguments(self,parser):
        parser.add_argument('peer_id',type=int)
        parser.add_argument('--reviewed',action='store_true')

    def handle(self,*args,**options):
        if not options['reviewed']:
            raise CommandError('Revise o arquivo gerado e execute com --reviewed para autorizar a alteração em runtime.')
        user=worker_user()
        with tenant_database_context(None,user.pk,central=True):
            try:
                peer=WireGuardPeer.objects.select_related('device','tenant').get(pk=options['peer_id'])
                result=apply_peer(peer)
            except (WireGuardPeer.DoesNotExist,WireGuardError) as exc:
                raise CommandError(str(exc)) from None
            AuditEvent.objects.create(tenant=peer.tenant,actor=user,action='aplicar/remover peer no servidor',object_type='wireguardpeer',object_id=peer.pk,fields_changed=['enabled','removal_confirmed_at'])
        self.stdout.write(result)
