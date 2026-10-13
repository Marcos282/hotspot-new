from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection


def verify_runtime_database():
    if settings.DEBUG:
        return
    if connection.vendor != 'postgresql':
        raise ImproperlyConfigured('PostgreSQL RLS is required in production.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user')
        if any(cursor.fetchone()):
            raise ImproperlyConfigured('Runtime database role must be NOSUPERUSER NOBYPASSRLS.')
        tables = ['tenants_tenant','tenants_tenantmembership','tenants_tenantsettings','tenants_device','tenants_accessplan','tenants_sale','tenants_payment','tenants_accesssession','tenants_hotspotconfiguration','tenants_brandimage','tenants_auditevent', 'operations_wireguardpeer','operations_devicehealth','operations_healthsample','operations_outage','operations_devicealert','operations_networkconfiguration','operations_controlauditevent','operations_saassubscription']
        cursor.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity AND EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid)", [tables])
        if cursor.fetchone()[0] != len(tables):
            raise ImproperlyConfigured('Apply tenant and central RLS migrations before serving production requests.')
        cursor.execute("SELECT count(*) FROM pg_class WHERE relname=ANY(%s) AND relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)", [tables])
        if cursor.fetchone()[0]:
            raise ImproperlyConfigured('Use a separate runtime role that does not own operational tables.')
