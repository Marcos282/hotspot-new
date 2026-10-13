from contextlib import contextmanager
from django.db import connection, transaction


@contextmanager
def tenant_database_context(tenant_id, user_id, *, central=False):
    # Transaction-local settings cannot leak when a pooled connection is reused.
    with transaction.atomic():
        previous = None
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('novainfo.tenant_id', true), current_setting('novainfo.user_id', true), current_setting('novainfo.central', true)")
                previous = cursor.fetchone()
                cursor.execute("SELECT set_config('novainfo.tenant_id', %s, true), set_config('novainfo.user_id', %s, true), set_config('novainfo.central', %s, true)", [str(tenant_id or ''), str(user_id or ''), 'true' if central else 'false'])
        try:
            yield
        finally:
            if previous is not None and not connection.needs_rollback:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('novainfo.tenant_id', %s, true), set_config('novainfo.user_id', %s, true), set_config('novainfo.central', %s, true)", [previous[0] or '', previous[1] or '', previous[2] or 'false'])
