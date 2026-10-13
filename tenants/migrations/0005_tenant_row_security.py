from django.db import migrations

TABLES = ['tenants_tenantsettings', 'tenants_device', 'tenants_accessplan', 'tenants_sale', 'tenants_payment', 'tenants_accesssession', 'tenants_hotspotconfiguration', 'tenants_brandimage', 'tenants_auditevent']
RELATIONS = [('tenants_sale', 'plan_id', 'tenants_accessplan'), ('tenants_payment', 'sale_id', 'tenants_sale'), ('tenants_accesssession', 'device_id', 'tenants_device')]


def install(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in TABLES:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        predicate = "tenant_id = NULLIF(current_setting('novainfo.tenant_id', true), '')::bigint AND EXISTS (SELECT 1 FROM tenants_tenantmembership m JOIN tenants_tenant t ON t.id = m.tenant_id WHERE m.tenant_id = tenant_id AND m.user_id = NULLIF(current_setting('novainfo.user_id', true), '')::bigint AND m.is_active AND t.is_active)"
        # Fully qualify the outer tenant key to avoid correlated-column ambiguity.
        predicate = predicate.replace('m.tenant_id = tenant_id', f'm.tenant_id = {table}.tenant_id')
        schema_editor.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})')
    for table in ['tenants_accessplan', 'tenants_sale', 'tenants_device']:
        schema_editor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {table}_id_tenant_unique UNIQUE (id, tenant_id)')
    for table, column, parent in RELATIONS:
        schema_editor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {table}_same_tenant FOREIGN KEY ({column}, tenant_id) REFERENCES {parent}(id, tenant_id)')


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table, column, parent in RELATIONS:
        schema_editor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {table}_same_tenant')
    for table in ['tenants_accessplan', 'tenants_sale', 'tenants_device']:
        schema_editor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {table}_id_tenant_unique')
    for table in TABLES:
        schema_editor.execute(f'DROP POLICY tenant_isolation ON {table}')
        schema_editor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [('tenants', '0004_accessplan_auditevent_brandimage_device_and_more')]
    operations = [migrations.RunPython(install, uninstall)]
