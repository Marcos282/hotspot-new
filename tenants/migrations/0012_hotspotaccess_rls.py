from django.db import migrations


def install(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    table='tenants_hotspotaccess'
    schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
    predicate=f"""tenant_id = NULLIF(current_setting('novainfo.tenant_id',true),'')::bigint AND EXISTS (
        SELECT 1 FROM tenants_tenantmembership m JOIN tenants_tenant t ON t.id=m.tenant_id
        WHERE m.tenant_id={table}.tenant_id AND m.user_id=NULLIF(current_setting('novainfo.user_id',true),'')::bigint AND m.is_active AND t.is_active)"""
    schema_editor.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})')
    schema_editor.execute(f'ALTER TABLE {table} ADD CONSTRAINT hotspotaccess_device_same_tenant FOREIGN KEY(device_id,tenant_id) REFERENCES tenants_device(id,tenant_id)')
    schema_editor.execute(f'ALTER TABLE {table} ADD CONSTRAINT hotspotaccess_plan_same_tenant FOREIGN KEY(plan_id,tenant_id) REFERENCES tenants_accessplan(id,tenant_id)')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    schema_editor.execute('ALTER TABLE tenants_hotspotaccess DROP CONSTRAINT hotspotaccess_device_same_tenant')
    schema_editor.execute('ALTER TABLE tenants_hotspotaccess DROP CONSTRAINT hotspotaccess_plan_same_tenant')
    schema_editor.execute('DROP POLICY tenant_isolation ON tenants_hotspotaccess')
    schema_editor.execute('ALTER TABLE tenants_hotspotaccess NO FORCE ROW LEVEL SECURITY')
    schema_editor.execute('ALTER TABLE tenants_hotspotaccess DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies=[('tenants','0011_hotspotaccess'),('operations','0007_saassubscription_saas_positive_monthly_amount')]
    operations=[migrations.RunPython(install,uninstall)]
