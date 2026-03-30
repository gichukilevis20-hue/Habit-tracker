from types import SimpleNamespace
from urllib.parse import urlparse

from django.utils import timezone


def _clean_value(value):
    if value is None:
        return ''
    return str(value).strip()


def _safe_avatar_url(url):
    cleaned_url = _clean_value(url)
    if not cleaned_url:
        return ''
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return ''
    return cleaned_url[:500]


def _split_full_name(full_name):
    normalized = _clean_value(full_name)
    if not normalized:
        return '', ''
    parts = normalized.split()
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


def _extra_data_from_sociallogin(sociallogin):
    account = getattr(sociallogin, 'account', None)
    extra_data = getattr(account, 'extra_data', None) or {}
    return extra_data if isinstance(extra_data, dict) else {}


def extract_social_profile_data(sociallogin, data=None):
    payload = data if isinstance(data, dict) else {}
    extra_data = _extra_data_from_sociallogin(sociallogin)
    account = getattr(sociallogin, 'account', None)
    provider = _clean_value(getattr(account, 'provider', ''))

    first_name = _clean_value(
        payload.get('first_name')
        or extra_data.get('given_name')
        or extra_data.get('first_name')
    )
    last_name = _clean_value(
        payload.get('last_name')
        or extra_data.get('family_name')
        or extra_data.get('last_name')
    )
    full_name = _clean_value(
        payload.get('name')
        or extra_data.get('name')
        or ' '.join(part for part in [first_name, last_name] if part)
    )
    if full_name and not (first_name or last_name):
        first_name, last_name = _split_full_name(full_name)

    email = _clean_value(payload.get('email') or extra_data.get('email')).lower()

    avatar_url = ''
    getter = getattr(account, 'get_avatar_url', None)
    if callable(getter):
        try:
            avatar_url = _safe_avatar_url(getter())
        except TypeError:
            avatar_url = ''

    if not avatar_url:
        picture_data = extra_data.get('picture')
        if isinstance(picture_data, dict):
            avatar_url = _safe_avatar_url(
                picture_data.get('data', {}).get('url') or picture_data.get('url')
            )
        else:
            avatar_url = _safe_avatar_url(picture_data)

    if not avatar_url:
        avatar_url = _safe_avatar_url(
            extra_data.get('avatar_url')
            or extra_data.get('avatar')
            or extra_data.get('photo')
            or payload.get('picture')
        )

    return {
        'provider': provider,
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'full_name': full_name,
        'avatar_url': avatar_url,
    }


def supplement_user_from_social_profile(user, social_profile, *, profile=None):
    if user is None:
        return False

    profile = profile or getattr(user, 'profile', None)
    user_fields_to_update = []
    profile_fields_to_update = []

    email = _clean_value(social_profile.get('email')).lower()
    if email and not _clean_value(user.email):
        user.email = email
        user_fields_to_update.append('email')

    first_name = _clean_value(social_profile.get('first_name'))
    last_name = _clean_value(social_profile.get('last_name'))
    full_name = _clean_value(social_profile.get('full_name'))
    if full_name and not (first_name or last_name):
        first_name, last_name = _split_full_name(full_name)

    if first_name and not _clean_value(user.first_name):
        user.first_name = first_name
        user_fields_to_update.append('first_name')
    if last_name and not _clean_value(user.last_name):
        user.last_name = last_name
        user_fields_to_update.append('last_name')

    if user_fields_to_update:
        user.save(update_fields=user_fields_to_update)

    if profile is not None:
        avatar_url = _safe_avatar_url(social_profile.get('avatar_url'))
        provider = _clean_value(social_profile.get('provider'))
        if provider and not _clean_value(profile.oauth_profile_source):
            profile.oauth_profile_source = provider
            profile_fields_to_update.append('oauth_profile_source')
        if (
            avatar_url
            and not profile.profile_image
            and not _clean_value(profile.oauth_profile_image_url)
        ):
            profile.oauth_profile_image_url = avatar_url
            profile_fields_to_update.append('oauth_profile_image_url')
        if profile_fields_to_update:
            profile.oauth_profile_synced_at = timezone.now()
            profile_fields_to_update.append('oauth_profile_synced_at')
            profile.save(update_fields=profile_fields_to_update)

    return bool(user_fields_to_update or profile_fields_to_update)


def sync_social_profile(user, sociallogin, data=None):
    if user is None:
        return False
    profile = getattr(user, 'profile', None)
    social_profile = extract_social_profile_data(sociallogin, data=data)
    return supplement_user_from_social_profile(user, social_profile, profile=profile)


def build_fake_sociallogin(provider, extra_data=None, avatar_url=''):
    class FakeAccount:
        def __init__(self, provider_name, details, avatar):
            self.provider = provider_name
            self.extra_data = details or {}
            self._avatar_url = avatar

        def get_avatar_url(self):
            return self._avatar_url

    return SimpleNamespace(account=FakeAccount(provider, extra_data, avatar_url))
