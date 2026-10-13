from importlib import import_module
from django.db import migrations


def install(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    policies=import_module('operations.migrations.0003_row_security')
    table='operations_saassubscription'
    predicate=f'(({policies.tenant_predicate(table)}) OR ({policies.CENTRAL}))'
    schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
    schema_editor.execute(f'CREATE POLICY subscription_read ON {table} FOR SELECT USING ({predicate})')
    request_predicate = f"""({policies.tenant_predicate(table)}) AND status='requested' AND provider_reference='' AND checkout_url=''
    AND requested_by_id=NULLIF(current_setting('novainfo.user_id',true),'')::bigint
    AND EXISTS (SELECT 1 FROM website_subscriptionplan p WHERE p.id={table}.plan_id AND p.is_active AND p.monthly_price={table}.monthly_amount AND p.monthly_price>0)
    AND EXISTS (SELECT 1 FROM tenants_tenantmembership m WHERE m.tenant_id={table}.tenant_id AND m.user_id={table}.requested_by_id AND m.is_active AND m.role IN ('owner','admin'))"""
    schema_editor.execute(f'CREATE POLICY subscription_request ON {table} FOR INSERT WITH CHECK (({request_predicate}) OR ({policies.CENTRAL}))')
    schema_editor.execute(f'CREATE POLICY subscription_manage ON {table} FOR UPDATE USING ({policies.CENTRAL}) WITH CHECK ({policies.CENTRAL})')
    schema_editor.execute(f'CREATE POLICY subscription_delete ON {table} FOR DELETE USING ({policies.CENTRAL})')


def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='postgresql':
        return
    for policy in ['subscription_read','subscription_request','subscription_manage','subscription_delete']:
        schema_editor.execute(f'DROP POLICY {policy} ON operations_saassubscription')
    schema_editor.execute('ALTER TABLE operations_saassubscription DISABLE ROW LEVEL SECURITY')
    schema_editor.execute('ALTER TABLE operations_saassubscription NO FORCE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies=[('operations','0005_saassubscription')]
    operations=[migrations.RunPython(install,uninstall)]
