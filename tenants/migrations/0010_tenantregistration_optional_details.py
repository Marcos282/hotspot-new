from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0009_tenantregistration'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantregistration',
            name='responsible_name',
            field=models.CharField(blank=True, max_length=120, verbose_name='nome do responsável'),
        ),
        migrations.AlterField(
            model_name='tenantregistration',
            name='phone',
            field=models.CharField(blank=True, max_length=32, verbose_name='telefone / WhatsApp'),
        ),
        migrations.AlterField(
            model_name='tenantregistration',
            name='city',
            field=models.CharField(blank=True, max_length=100, verbose_name='cidade'),
        ),
    ]
