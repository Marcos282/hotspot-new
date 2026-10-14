"""Authenticate existing Django accounts by their unique email address."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get('email', username)
        if not email or password is None:
            return None
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email.strip())
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
