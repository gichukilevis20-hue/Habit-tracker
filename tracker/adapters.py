from django.contrib.auth import get_user_model
from django.utils.text import slugify

try:
    from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
except ImportError:  # pragma: no cover - exercised only when allauth is not installed
    DefaultSocialAccountAdapter = object

from .social_profiles import extract_social_profile_data, sync_social_profile


class TrackerSocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        social_profile = extract_social_profile_data(sociallogin, data=data)
        email = social_profile['email']
        first_name = social_profile['first_name']
        last_name = social_profile['last_name']
        full_name = social_profile['full_name'] or 'Habit Tracker user'

        if email and not user.email:
            user.email = email
        if first_name and not user.first_name:
            user.first_name = first_name
        if last_name and not user.last_name:
            user.last_name = last_name
        if not getattr(user, 'username', ''):
            user.username = self._build_unique_username(email=email, full_name=full_name, uid=str(sociallogin.account.uid))

        return user

    def pre_social_login(self, request, sociallogin):
        super().pre_social_login(request, sociallogin)
        user = getattr(sociallogin, 'user', None)
        if getattr(user, 'pk', None):
            sync_social_profile(user, sociallogin)

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        sync_social_profile(user, sociallogin)
        return user

    def _build_unique_username(self, email, full_name, uid):
        user_model = get_user_model()
        candidates = [
            email.split('@')[0] if email else '',
            slugify(full_name),
            f'user-{uid[:8]}',
        ]
        base_username = next((candidate for candidate in candidates if candidate), f'user-{uid[:8]}')
        base_username = base_username[:150]
        username = base_username
        suffix = 1

        while user_model.objects.filter(username=username).exists():
            suffix += 1
            trimmed_base = base_username[: max(1, 150 - len(str(suffix)) - 1)]
            username = f'{trimmed_base}-{suffix}'

        return username
