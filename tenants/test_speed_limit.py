from django.test import SimpleTestCase
from tenants.forms import AccessPlanForm


class SpeedLimitTests(SimpleTestCase):
    def form(self,value):
        return AccessPlanForm({'name':'Plano','duration_minutes':60,'price':'10,50','speed_limit':value,'enabled':'on'})

    def test_simple_numbers_and_flexible_units_are_converted(self):
        for value,expected in [('10','10M/10M'),('5/10','5M/10M'),('5M/10M','5M/10M'),
                               ('10 Mbps','10M/10M'),('5 mbps / 10 mbps','5M/10M'),
                               ('2,5','2500k/2500k'),('2.5/10','2500k/10M'),('500k/1M','500k/1M'),
                               ('1G','1000M/1000M'),('10 Mb/s','10M/10M')]:
            with self.subTest(value=value):
                form=self.form(value)
                self.assertTrue(form.is_valid(),form.errors)
                self.assertEqual(form.cleaned_data['speed_limit'],expected)

    def test_blank_or_zero_does_not_block_registration(self):
        for value in ['', '0','0/0']:
            form=self.form(value)
            self.assertTrue(form.is_valid(),form.errors)
            self.assertEqual(form.cleaned_data['speed_limit'],'')

    def test_invalid_speeds_return_readable_numeric_error(self):
        for value in ['abc','-5','5/10/20','5M;command','NaN','1e8','0.0000001bps']:
            form=self.form(value)
            self.assertFalse(form.is_valid())
            self.assertNotIn('Use um limite como 5M/10M.',str(form.errors))

    def test_help_does_not_require_routeros_units(self):
        html=self.form('').as_p()
        self.assertIn('Velocidade em Mbps',html)
        self.assertNotIn('Use um limite como 5M/10M.',html)
        self.assertNotIn('Exemplo: 5M/10M',html)
