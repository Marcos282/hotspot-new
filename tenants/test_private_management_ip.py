from django.test import SimpleTestCase
from tenants.forms import DeviceForm
from operations.forms import CentralDeviceForm


class PrivateManagementIPTests(SimpleTestCase):
    def form(self,address):
        return DeviceForm({'name':'Router','management_ip':address,'enabled':'on'})

    def test_all_private_ranges_and_shared_provider_addresses(self):
        for address in ['10.0.0.1','10.255.255.254','172.16.0.1','172.31.255.254',
                        '192.168.0.1','192.168.255.254','100.64.0.1','100.127.255.254','fc00::1','fdff::1']:
            with self.subTest(address=address):
                form=self.form(address)
                self.assertTrue(form.is_valid(),form.errors)

    def test_public_loopback_linklocal_and_invalid_are_rejected(self):
        for address in ['8.8.8.8','172.15.0.1','172.32.0.1','100.63.255.254','100.128.0.1',
                        '127.0.0.1','169.254.1.1','0.0.0.0','224.0.0.1','::1','fe80::1','2001:4860:4860::8888','192.168.500.1']:
            with self.subTest(address=address):
                self.assertIn('management_ip',self.form(address).errors)

    def test_mask_and_spaces_are_normalized_without_changing_host(self):
        for entered,expected in [(' 192.168.1.7/24 ','192.168.1.7'),('10.20.30.40/16','10.20.30.40'),('fd01::7/64','fd01::7'),('::ffff:192.168.1.7','192.168.1.7')]:
            form=self.form(entered)
            self.assertTrue(form.is_valid(),form.errors)
            self.assertEqual(form.cleaned_data['management_ip'],expected)
        self.assertFalse(self.form('192.168.1.1/99').is_valid())
        self.assertFalse(self.form('8.8.8.8/24').is_valid())

    def test_central_form_uses_same_validation(self):
        field=CentralDeviceForm.base_fields['management_ip']
        self.assertEqual(field.clean('192.168.254.250/24'),'192.168.254.250')
        self.assertEqual(field.clean('100.100.100.1'),'100.100.100.1')
