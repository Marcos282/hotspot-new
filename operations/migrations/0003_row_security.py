from django.db import migrations

OLD_TABLES=['tenants_tenantsettings','tenants_device','tenants_accessplan','tenants_sale','tenants_payment','tenants_accesssession','tenants_hotspotconfiguration','tenants_brandimage','tenants_auditevent']
NEW_TABLES=['operations_wireguardpeer','operations_devicehealth','operations_healthsample','operations_outage','operations_devicealert']
SYSTEM_TABLES=['operations_networkconfiguration','operations_controlauditevent']
CENTRAL="""current_setting('novainfo.central',true) = 'true' AND EXISTS (
 SELECT 1 FROM auth_user u WHERE u.id = NULLIF(current_setting('novainfo.user_id',true),'')::bigint AND u.is_active AND u.is_staff
 AND (u.is_superuser OR EXISTS (
 SELECT 1 FROM auth_user_user_permissions up JOIN auth_permission p ON p.id=up.permission_id JOIN django_content_type ct ON ct.id=p.content_type_id
 WHERE up.user_id=u.id AND p.codename='manage_network' AND ct.app_label='operations'
 ) OR EXISTS (
 SELECT 1 FROM auth_user_groups ug JOIN auth_group_permissions gp ON gp.group_id=ug.group_id JOIN auth_permission p ON p.id=gp.permission_id JOIN django_content_type ct ON ct.id=p.content_type_id
 WHERE ug.user_id=u.id AND p.codename='manage_network' AND ct.app_label='operations'
 )) )"""


def tenant_predicate(table):
    return f"""tenant_id = NULLIF(current_setting('novainfo.tenant_id', true), '')::bigint AND EXISTS (
    SELECT 1 FROM tenants_tenantmembership m JOIN tenants_tenant t ON t.id=m.tenant_id
    WHERE m.tenant_id={table}.tenant_id AND m.user_id=NULLIF(current_setting('novainfo.user_id',true),'')::bigint AND m.is_active AND t.is_active)"""


def install(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    if apps.get_model('auth','User')._meta.db_table != 'auth_user':
        raise RuntimeError('Adapte as políticas centrais ao modelo de autenticação customizado antes da migração.')
    for table in OLD_TABLES+NEW_TABLES:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        if table in OLD_TABLES:
            schema_editor.execute(f'DROP POLICY tenant_isolation ON {table}')
        predicate=f'(({tenant_predicate(table)}) OR ({CENTRAL}))'
        schema_editor.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})')
    for table in SYSTEM_TABLES:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'CREATE POLICY central_only ON {table} USING ({CENTRAL}) WITH CHECK ({CENTRAL})')
    # Relationships are checked by the database even when Django validation is bypassed.
    schema_editor.execute('ALTER TABLE operations_outage ADD CONSTRAINT operations_outage_id_tenant UNIQUE (id,tenant_id)')
    for table,column,parent in [('operations_wireguardpeer','device_id','tenants_device'),('operations_devicehealth','device_id','tenants_device'),('operations_healthsample','device_id','tenants_device'),('operations_outage','device_id','tenants_device'),('operations_devicealert','outage_id','operations_outage')]:
        schema_editor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {table}_same_tenant FOREIGN KEY ({column},tenant_id) REFERENCES {parent}(id,tenant_id)')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    for table in NEW_TABLES:
        schema_editor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {table}_same_tenant')
    schema_editor.execute('ALTER TABLE operations_outage DROP CONSTRAINT operations_outage_id_tenant')
    for table in OLD_TABLES+NEW_TABLES:
        schema_editor.execute(f'DROP POLICY tenant_isolation ON {table}')
        if table in OLD_TABLES:
            predicate=tenant_predicate(table)
            schema_editor.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({predicate}) WITH CHECK ({predicate})')
        else:
            schema_editor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')
            schema_editor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
    for table in SYSTEM_TABLES:
        schema_editor.execute(f'DROP POLICY central_only ON {table}')
        schema_editor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies=[('operations','0002_controlauditevent'),('tenants','0006_accesssession_router_session_id_and_more')]
    operations=[migrations.RunPython(install,uninstall)]
