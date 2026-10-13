from importlib import import_module
from django.db import migrations

CENTRAL=import_module('operations.migrations.0003_row_security').CENTRAL


def install(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='novainfo_resolver'")
        if not cursor.fetchone():
            schema_editor.execute('CREATE ROLE novainfo_resolver NOLOGIN NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT')
    schema_editor.execute('GRANT USAGE ON SCHEMA public TO novainfo_resolver')
    schema_editor.execute('GRANT SELECT ON tenants_tenant TO novainfo_resolver')
    schema_editor.execute("""CREATE FUNCTION public.novainfo_resolve_tenant(requested_slug text)
    RETURNS TABLE(id bigint, name varchar, slug varchar, is_active boolean)
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path=pg_catalog,public AS $$
    SELECT t.id,t.name,t.slug,t.is_active FROM public.tenants_tenant t
    WHERE t.slug=requested_slug AND t.is_active
    $$""")
    schema_editor.execute('ALTER FUNCTION public.novainfo_resolve_tenant(text) OWNER TO novainfo_resolver')
    # Exposes only already-public login identity, never tenant contact/VPN settings.
    schema_editor.execute('GRANT EXECUTE ON FUNCTION public.novainfo_resolve_tenant(text) TO PUBLIC')
    for table in ['tenants_tenant','tenants_tenantmembership']:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
    membership="user_id=NULLIF(current_setting('novainfo.user_id',true),'')::bigint AND (NULLIF(current_setting('novainfo.tenant_id',true),'') IS NULL OR tenant_id=NULLIF(current_setting('novainfo.tenant_id',true),'')::bigint)"
    schema_editor.execute(f'CREATE POLICY membership_read ON tenants_tenantmembership FOR SELECT USING (({membership}) OR ({CENTRAL}))')
    schema_editor.execute(f'CREATE POLICY membership_manage ON tenants_tenantmembership FOR ALL USING ({CENTRAL}) WITH CHECK ({CENTRAL})')
    tenant="id=NULLIF(current_setting('novainfo.tenant_id',true),'')::bigint AND is_active AND EXISTS (SELECT 1 FROM public.tenants_tenantmembership m WHERE m.tenant_id=tenants_tenant.id AND m.user_id=NULLIF(current_setting('novainfo.user_id',true),'')::bigint AND m.is_active)"
    schema_editor.execute(f'CREATE POLICY tenant_registry_read ON tenants_tenant FOR SELECT USING (({tenant}) OR ({CENTRAL}))')
    schema_editor.execute(f'CREATE POLICY tenant_registry_manage ON tenants_tenant FOR ALL USING ({CENTRAL}) WITH CHECK ({CENTRAL})')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    for table,policies in [('tenants_tenant',['tenant_registry_read','tenant_registry_manage']),('tenants_tenantmembership',['membership_read','membership_manage'])]:
        for policy in policies:
            schema_editor.execute(f'DROP POLICY {policy} ON {table}')
        schema_editor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
    schema_editor.execute('DROP FUNCTION public.novainfo_resolve_tenant(text)')
    # Resolver role may be used by another database; do not remove it globally.


class Migration(migrations.Migration):
    dependencies=[('operations','0003_row_security')]
    operations=[migrations.RunPython(install,uninstall)]
