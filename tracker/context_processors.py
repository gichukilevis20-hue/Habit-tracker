from collections import Counter

from django.conf import settings
from django.utils import timezone

from .models import Habit


SOCIAL_PROVIDER_CATALOG = [
    {'id': 'google', 'label': 'Google', 'icon': 'fa-brands fa-google'},
    {'id': 'microsoft', 'label': 'Microsoft', 'icon': 'fa-brands fa-microsoft'},
    {'id': 'github', 'label': 'GitHub', 'icon': 'fa-brands fa-github'},
    {'id': 'facebook', 'label': 'Facebook', 'icon': 'fa-brands fa-facebook-f'},
]


def configured_social_login_providers():
    if not getattr(settings, 'SOCIAL_LOGIN_ENABLED', False):
        return []

    provider_settings = getattr(settings, 'SOCIALACCOUNT_PROVIDERS', {})
    available_providers = []

    for provider in SOCIAL_PROVIDER_CATALOG:
        configuration = provider_settings.get(provider['id'], {})
        is_configured = bool(configuration.get('APP') or configuration.get('APPS'))
        available_providers.append(
            {
                **provider,
                'login_url': f"/accounts/{provider['id']}/login/",
                'is_configured': is_configured,
            }
        )

    return available_providers


def app_shell(request):
    social_login_providers = configured_social_login_providers()
    context = {
        'social_login_providers': social_login_providers,
        'social_login_configured_count': sum(1 for provider in social_login_providers if provider['is_configured']),
        'social_login_unconfigured_count': sum(1 for provider in social_login_providers if not provider['is_configured']),
    }

    if not request.user.is_authenticated:
        return context

    habits = list(Habit.objects.filter(user=request.user).only('id', 'title', 'is_active', 'time_of_day', 'area'))
    time_of_day_counter = Counter()
    area_counter = Counter()

    for habit in habits:
        if habit.time_of_day:
            slots = [slot.strip() for slot in habit.time_of_day.split(',') if slot.strip()]
        else:
            slots = ['Any Time']

        for slot in slots:
            time_of_day_counter[slot] += 1

        area_counter[(habit.area or 'Uncategorized').strip() or 'Uncategorized'] += 1

    current_hour = timezone.localtime().hour
    current_slot = 'Morning'
    if current_hour >= 17:
        current_slot = 'Evening'
    elif current_hour >= 12:
        current_slot = 'Afternoon'

    default_time_slots = [
        ('Morning', 'fa-cloud-sun'),
        ('Afternoon', 'fa-sun'),
        ('Evening', 'fa-moon'),
    ]

    shell = {
        'active_count': sum(1 for habit in habits if habit.is_active),
        'archived_count': sum(1 for habit in habits if not habit.is_active),
        'time_of_day': [
            {
                'label': label,
                'icon': icon,
                'count': time_of_day_counter.get(label, 0),
                'is_current': label == current_slot,
            }
            for label, icon in default_time_slots
        ],
        'areas': [
            {'label': label, 'count': count}
            for label, count in sorted(area_counter.items(), key=lambda item: item[0].lower())
        ],
    }
    context['app_shell'] = shell
    return context
