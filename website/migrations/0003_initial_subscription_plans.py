from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('website', 'SubscriptionPlan')
    for position, (name, description) in enumerate([
        ('Starter', 'Para pequenos estabelecimentos que desejam começar a comercializar internet.'),
        ('Profissional', 'Para negócios com maior volume de clientes e necessidade de recursos avançados.'),
        ('Empresarial', 'Para provedores e empresas que administram múltiplos equipamentos e estabelecimentos.'),
    ]):
        Plan.objects.using(schema_editor.connection.alias).get_or_create(name=name, defaults={'description': description, 'position': position, 'is_featured': name == 'Profissional'})


class Migration(migrations.Migration):
    dependencies = [('website', '0002_subscriptionplan')]
    operations = [migrations.RunPython(seed_plans, migrations.RunPython.noop)]
