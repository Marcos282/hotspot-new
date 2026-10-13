from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from tenants.models import Tenant, TenantMembership


@override_settings(DEBUG=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', DEFAULT_FROM_EMAIL='conta@example.com')
class AccountTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.tenant = Tenant.objects.create(name='Hotel', slug='hotel')
        self.user = get_user_model().objects.create_user('member', email='member@example.com', password='Strong-test-123!')
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, role='owner')
        self.host = {'HTTP_HOST': 'hotel.novainfo.com.br'}

    def test_all_panel_routes_require_authentication(self):
        for path in ['/painel/', '/painel/equipamentos/', '/painel/relatorios/', '/painel/assinatura/', '/painel/imagens/1/', '/painel/future/']:
            response = self.client.get(path, **self.host)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)

    def test_signup_confirmation_never_grants_membership(self):
        response = self.client.post('/accounts/cadastro/', {'username': 'new', 'email': 'new@example.com', 'password1': 'Secure-new-789!', 'password2': 'Secure-new-789!'}, **self.host)
        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username='new')
        self.assertFalse(user.is_active)
        link = mail.outbox[0].body.splitlines()[1]
        path = '/' + link.split('/', 3)[3]
        self.client.get(path, **self.host)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.client.post(path, **self.host)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(TenantMembership.objects.filter(user=user).exists())
        self.client.force_login(user)
        self.assertEqual(self.client.get('/painel/', **self.host).status_code, 404)
        self.assertEqual(self.client.post(path, **self.host).status_code, 400)

    def test_reset_is_generic_and_token_is_single_use(self):
        response = self.client.post('/accounts/recuperar/', {'email': self.user.email}, **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        link = next(line for line in mail.outbox[0].body.splitlines() if line.startswith('http'))
        path = '/' + link.split('/', 3)[3]
        response = self.client.get(path, **self.host)
        response = self.client.post(response.url, {'new_password1': 'Changed-strong-456!', 'new_password2': 'Changed-strong-456!'}, **self.host)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Changed-strong-456!'))
        response = self.client.get(path, **self.host)
        self.assertContains(response, 'expirou')
        response = self.client.post('/accounts/recuperar/', {'email': 'unknown@example.com'}, **self.host)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    @patch('tenants.account.send_mail', side_effect=RuntimeError('failure'))
    def test_delivery_failure_does_not_leave_unusable_signup(self, send):
        self.client.post('/accounts/cadastro/', {'username': 'new', 'email': 'new@example.com', 'password1': 'Secure-new-789!', 'password2': 'Secure-new-789!'}, **self.host)
        self.assertFalse(get_user_model().objects.filter(username='new').exists())

    def test_login_attempts_are_limited(self):
        for _ in range(10):
            response = self.client.post('/accounts/login/', {'username': 'member', 'password': 'wrong'}, **self.host)
            self.assertEqual(response.status_code, 200)
        response = self.client.post('/accounts/login/', {'username': 'member', 'password': 'wrong'}, **self.host)
        self.assertEqual(response.status_code, 429)


@override_settings(RESEND_API_KEY='test-key', DEFAULT_FROM_EMAIL='conta@example.com')
class ResendBackendTests(TestCase):
    @patch('tenants.email_backend.urlopen')
    def test_request_uses_resend_and_does_not_send_passwords(self, opener):
        import io
        import json
        from django.core.mail import EmailMessage
        from tenants.email_backend import EmailBackend
        opener.return_value.__enter__.return_value = io.BytesIO(b'{"id":"message-id"}')
        message = EmailMessage('Recuperar senha', 'Link de redefinição', to=['member@example.com'])
        self.assertEqual(EmailBackend().send_messages([message]), 1)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.resend.com/emails')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(json.loads(request.data)['to'], ['member@example.com'])

    @patch('tenants.email_backend.urlopen', side_effect=OSError('secret details'))
    def test_delivery_error_is_sanitized(self, opener):
        from django.core.mail import EmailMessage
        from tenants.email_backend import EmailBackend
        with self.assertRaisesRegex(RuntimeError, 'Resend'):
            EmailBackend().send_messages([EmailMessage('Assunto', 'Texto', to=['member@example.com'])])
