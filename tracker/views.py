import base64
import csv
import datetime
import io
import json
import os
from collections import defaultdict
from decimal import Decimal

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login as auth_login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.db.models import Count, Max, Prefetch, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import (
    AdminDonationForm,
    AdminEmailComposeForm,
    AdminHabitForm,
    AdminProfileForm,
    AdminUserChangeForm,
    AdminUserCreateForm,
    ContactForm,
    DonationForm,
    HabitEntryForm,
    HabitForm,
    LoginForm,
    ProfileForm,
    SignUpForm,
    WeeklyReviewForm,
)
from .models import AdminEmail, ContactMessage, Donation, Habit, HabitEntry, Profile, WeeklyReview
from .payments import (
    DarajaError,
    build_bitcoin_uri,
    daraja_configuration_errors,
    daraja_is_configured,
    extract_stk_callback_details,
    initiate_mpesa_stk_push,
)
from .reminders import is_habit_due_on


CAROUSEL_QUOTES = [
    "Small steps every day build big habits.",
    "Consistency creates momentum.",
    "Progress over perfection.",
    "Your habits shape your future.",
    "One good decision can change your day.",
]

COMPLETION_QUOTES = [
    "Momentum looks good on you.",
    "You showed up today. That matters.",
    "The streak is real. Keep protecting it.",
    "Another vote for the person you want to become.",
    "Your future self will thank you for this entry.",
]

ATOMIC_WINDOW_DAYS = 14
PATTERN_MONTH_SPAN = 4
SCORE_WINDOW_DAYS = 21
HISTORY_WINDOW_DAYS = 14
TOP_STREAK_LIMIT = 5


def _sandbox_contact_email():
    return getattr(settings, 'SANDBOX_GMAIL_ADDRESS', 'habittracker001@gmail.com').strip() or 'habittracker001@gmail.com'


def _contact_email_delivery_context():
    sandbox_email = _sandbox_contact_email()
    smtp_sender_email = getattr(settings, 'EMAIL_HOST_USER', '').strip() or sandbox_email
    email_backend = getattr(settings, 'EMAIL_BACKEND', '')
    if email_backend != 'django.core.mail.backends.smtp.EmailBackend':
        transport_label = 'Console backend'
    elif getattr(settings, 'EMAIL_USE_SSL', False):
        transport_label = 'SMTP over SSL'
    elif getattr(settings, 'EMAIL_USE_TLS', False):
        transport_label = 'SMTP with TLS'
    else:
        transport_label = 'SMTP'
    return {
        'sandbox_recipient_email': sandbox_email,
        'smtp_sender_email': smtp_sender_email,
        'smtp_sender_matches_sandbox': smtp_sender_email.lower() == sandbox_email.lower(),
        'smtp_transport_label': transport_label,
        'smtp_enabled': email_backend == 'django.core.mail.backends.smtp.EmailBackend',
    }


def generate_qr_data_uri(data):
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buffered = io.BytesIO()
    img.save(buffered, format='PNG')
    img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return f'data:image/png;base64,{img_str}'


def load_electrum_addresses():
    path = os.path.join(settings.BASE_DIR, '..', 'electrum_requests.json')
    if not os.path.exists(path):
        path = os.path.join(settings.BASE_DIR, 'electrum_requests.json')

    addresses = []
    try:
        with open(path, 'r', encoding='utf-8') as file_handle:
            data = json.load(file_handle)
            for item in data:
                for output in item.get('outputs', []):
                    if len(output) >= 2 and output[1].startswith('bc1'):
                        addresses.append(output[1])
    except Exception:
        pass
    return list(dict.fromkeys(addresses))


def merge_payment_payload(existing_payload, **updates):
    payload = {}
    if existing_payload:
        try:
            payload = json.loads(existing_payload)
        except json.JSONDecodeError:
            payload = {'legacy_value': existing_payload}

    if not isinstance(payload, dict):
        payload = {'legacy_value': payload}

    for key, value in updates.items():
        if value is not None:
            payload[key] = value

    return json.dumps(payload, default=str)


def week_bounds(day):
    week_start = day - datetime.timedelta(days=day.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end


def compute_streak(entry_map, today):
    streak = 0
    cursor = today
    while cursor in entry_map and entry_map[cursor].completed:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak


def month_bounds(day):
    first_day = day.replace(day=1)
    next_month = (first_day + datetime.timedelta(days=32)).replace(day=1)
    last_day = next_month - datetime.timedelta(days=1)
    return first_day, last_day


def _date_range(start, end):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += datetime.timedelta(days=1)


def _shift_month(month_start, offset):
    month_index = (month_start.month - 1) + offset
    year = month_start.year + (month_index // 12)
    month = (month_index % 12) + 1
    return datetime.date(year, month, 1)


def _format_date_window(start, end):
    if start == end:
        return start.strftime('%b %d')
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b %d')} to {end.strftime('%d')}"
    return f"{start.strftime('%b %d')} to {end.strftime('%b %d')}"


def _gradient_fill_for_strength(strength):
    if strength <= 0:
        return ''
    normalized = max(0, min(strength, 100)) / 100
    orange_alpha = 0.16 + (normalized * 0.24)
    blue_alpha = 0.12 + (normalized * 0.3)
    return (
        f'background: linear-gradient(135deg, '
        f'rgba(255, 122, 89, {orange_alpha:.2f}), '
        f'rgba(50, 86, 255, {blue_alpha:.2f}));'
    )


def _period_progress_snapshot(label, start, end, habits, entry_maps):
    scheduled = 0
    completed = 0

    for habit in habits:
        if not habit.is_active:
            continue

        entry_map = entry_maps.get(habit.id, {})
        for day in _date_range(start, end):
            if not is_habit_due_on(habit, day):
                continue
            scheduled += 1
            entry = entry_map.get(day)
            if entry and entry.completed:
                completed += 1

    percent = round((completed / scheduled) * 100, 1) if scheduled else 0
    return {
        'label': label,
        'completed': completed,
        'target': scheduled,
        'percent': percent,
        'progress_label': f'{completed}/{scheduled}' if scheduled else 'No scheduled check-ins',
    }


def _build_pattern_atlas(habits, entry_maps, review_days, today):
    current_month_start = today.replace(day=1)
    month_starts = [
        _shift_month(current_month_start, offset)
        for offset in range(-(PATTERN_MONTH_SPAN - 1), 1)
    ]
    first_grid_start = month_starts[0] - datetime.timedelta(days=month_starts[0].weekday())
    last_month_end = month_bounds(month_starts[-1])[1]
    last_grid_end = last_month_end + datetime.timedelta(days=(6 - last_month_end.weekday()))

    day_rollup = {
        day: {
            'date': day,
            'scheduled': 0,
            'completed_due': 0,
            'completed_entries': 0,
            'logged_entries': 0,
            'small_wins': 0,
            'quantity_total': 0,
            'has_reviews': day in review_days,
        }
        for day in _date_range(first_grid_start, last_grid_end)
    }

    for habit in habits:
        entry_map = entry_maps.get(habit.id, {})
        for day in day_rollup:
            if is_habit_due_on(habit, day):
                day_rollup[day]['scheduled'] += 1
                entry = entry_map.get(day)
                if entry and entry.completed:
                    day_rollup[day]['completed_due'] += 1

        for entry in entry_map.values():
            if entry.date not in day_rollup:
                continue
            day_rollup[entry.date]['logged_entries'] += 1
            day_rollup[entry.date]['quantity_total'] += serialize_amount(entry.quantity)
            if _entry_counts_as_small_win(entry):
                day_rollup[entry.date]['small_wins'] += 1
            if entry.completed:
                day_rollup[entry.date]['completed_entries'] += 1

    month_panels = []
    for month_start in month_starts:
        month_end = month_bounds(month_start)[1]
        grid_start = month_start - datetime.timedelta(days=month_start.weekday())
        grid_end = month_end + datetime.timedelta(days=(6 - month_end.weekday()))
        weeks = []
        week = []
        month_completed_total = 0
        month_target_total = 0

        for day in _date_range(grid_start, grid_end):
            stats = day_rollup[day]
            completion_ratio = (
                stats['completed_due'] / stats['scheduled']
                if stats['scheduled']
                else (1 if stats['completed_entries'] else 0)
            )
            strength = 0
            if stats['completed_entries']:
                strength = max(32, round(completion_ratio * 100))

            day_payload = {
                'date': day,
                'day_number': day.day,
                'completed_entries': stats['completed_entries'],
                'logged_entries': stats['logged_entries'],
                'scheduled': stats['scheduled'],
                'completion_rate': round(completion_ratio * 100, 1) if strength else 0,
                'is_current_month': day.month == month_start.month,
                'is_today': day == today,
                'has_reviews': stats['has_reviews'],
                'style': _gradient_fill_for_strength(strength),
            }
            week.append(day_payload)

            if day.month == month_start.month:
                month_completed_total += stats['completed_entries']
                month_target_total += stats['scheduled']

            if len(week) == 7:
                weeks.append(week)
                week = []

        month_panels.append(
            {
                'label': month_start.strftime('%B %Y'),
                'weeks': weeks,
                'completed_total': month_completed_total,
                'target_total': month_target_total,
                'completion_rate': round((month_completed_total / month_target_total) * 100, 1)
                if month_target_total
                else 0,
            }
        )

    streak_runs = []
    active_run = None
    for day in _date_range(month_starts[0], last_month_end):
        stats = day_rollup[day]
        if stats['completed_entries']:
            if active_run and day == active_run['end'] + datetime.timedelta(days=1):
                active_run['end'] = day
                active_run['days'] += 1
                active_run['completed_total'] += stats['completed_entries']
            else:
                active_run = {
                    'start': day,
                    'end': day,
                    'days': 1,
                    'completed_total': stats['completed_entries'],
                }
                streak_runs.append(active_run)
        else:
            active_run = None

    ordered_streaks = sorted(
        streak_runs,
        key=lambda run: (run['days'], run['completed_total'], run['end']),
        reverse=True,
    )[:TOP_STREAK_LIMIT]
    max_streak_days = max((run['days'] for run in ordered_streaks), default=1)
    best_streaks = [
        {
            'label': _format_date_window(run['start'], run['end']),
            'days': run['days'],
            'width': max(18, round((run['days'] / max_streak_days) * 100)),
            'completed_total': run['completed_total'],
        }
        for run in ordered_streaks
    ]

    weekday_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    weekday_counts = [0] * 7
    for day in _date_range(month_starts[0], last_month_end):
        weekday_counts[day.weekday()] += day_rollup[day]['completed_entries']
    max_weekday_count = max(weekday_counts) if any(weekday_counts) else 1
    weekday_frequency = [
        {
            'label': weekday_labels[index],
            'count': count,
            'size': round(3.15 + ((count / max_weekday_count) * 2.35), 2) if count else 3.15,
            'width': max(12, round((count / max_weekday_count) * 100)) if count else 12,
            'is_peak': count == max_weekday_count and count > 0,
        }
        for index, count in enumerate(weekday_counts)
    ]

    week_start, _week_end = week_bounds(today)
    month_start, _month_end = month_bounds(today)
    year_start = today.replace(month=1, day=1)
    progress_bars = [
        _period_progress_snapshot('Today', today, today, habits, entry_maps),
        _period_progress_snapshot('This week', week_start, today, habits, entry_maps),
        _period_progress_snapshot('This month', month_start, today, habits, entry_maps),
        _period_progress_snapshot('This year', year_start, today, habits, entry_maps),
    ]

    score_days = [today - datetime.timedelta(days=index) for index in reversed(range(SCORE_WINDOW_DAYS))]
    score_values = []
    for day in score_days:
        stats = day_rollup.get(day)
        if not stats or not stats['scheduled']:
            score_values.append(None)
        else:
            score_values.append(round((stats['completed_due'] / stats['scheduled']) * 100, 1))
    non_null_scores = [value for value in score_values if value is not None]

    history_days = [today - datetime.timedelta(days=index) for index in reversed(range(HISTORY_WINDOW_DAYS))]
    history_values = [day_rollup.get(day, {}).get('completed_entries', 0) for day in history_days]
    history_peak_value = max(history_values) if history_values else 0
    history_peak_day = ''
    if history_values and history_peak_value:
        peak_index = history_values.index(history_peak_value)
        history_peak_day = history_days[peak_index].strftime('%b %d')

    return {
        'range_label': f"{month_starts[0].strftime('%b %Y')} to {month_starts[-1].strftime('%b %Y')}",
        'month_panels': month_panels,
        'best_streaks': best_streaks,
        'weekday_frequency': weekday_frequency,
        'progress_bars': progress_bars,
        'score_chart': {
            'labels': [day.strftime('%b %d') for day in score_days],
            'values': score_values,
            'average': round(sum(non_null_scores) / len(non_null_scores), 1) if non_null_scores else 0,
            'best': max(non_null_scores) if non_null_scores else 0,
        },
        'history_chart': {
            'labels': [day.strftime('%b %d') for day in history_days],
            'values': history_values,
            'peak_value': history_peak_value,
            'peak_day': history_peak_day,
        },
    }


def serialize_amount(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _entry_counts_as_small_win(entry):
    if not entry:
        return False
    return entry.completed or entry.quantity > 0 or bool((entry.note or '').strip())


def _current_streak_from_dates(success_dates, today):
    streak = 0
    cursor = today
    while cursor in success_dates:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak


def _longest_streak_from_dates(success_dates):
    longest = 0
    streak = 0
    previous_day = None

    for day in sorted(success_dates):
        if previous_day and day == previous_day + datetime.timedelta(days=1):
            streak += 1
        else:
            streak = 1
        longest = max(longest, streak)
        previous_day = day

    return longest


def _streak_series(success_dates, days):
    series = []
    streak = 0
    previous_day = None

    for day in days:
        if day in success_dates:
            if previous_day and previous_day in success_dates and day == previous_day + datetime.timedelta(days=1):
                streak += 1
            else:
                streak = 1
        else:
            streak = 0
        series.append(streak)
        previous_day = day

    return series


def _habit_atomic_metrics(habit, entries, today, window_days=ATOMIC_WINDOW_DAYS):
    entry_map = {entry.date: entry for entry in entries}
    small_win_dates = {
        entry.date
        for entry in entries
        if entry.date <= today and _entry_counts_as_small_win(entry)
    }
    completed_dates = {
        entry.date
        for entry in entries
        if entry.date <= today and entry.completed
    }
    window_start = today - datetime.timedelta(days=window_days - 1)
    window_dates = [window_start + datetime.timedelta(days=index) for index in range(window_days)]
    small_win_series = [1 if day in small_win_dates else 0 for day in window_dates]
    streak_series = _streak_series(small_win_dates, window_dates)

    return {
        'window_label': f'Last {window_days} days',
        'window_dates': window_dates,
        'small_win_dates': small_win_dates,
        'completed_dates': completed_dates,
        'current_streak': _current_streak_from_dates(small_win_dates, today),
        'best_streak': _longest_streak_from_dates(small_win_dates),
        'small_wins': sum(small_win_series),
        'consistency_rate': round((sum(small_win_series) / max(1, window_days)) * 100, 1),
        'small_win_series': small_win_series,
        'streak_series': streak_series,
        'quantity_series': [entry_map.get(day).quantity if entry_map.get(day) else 0 for day in window_dates],
        'days': [
            {
                'label': day.strftime('%a')[0],
                'title': day.strftime('%a, %b %d'),
                'won': day in small_win_dates,
                'completed': day in completed_dates,
            }
            for day in window_dates
        ],
    }


def user_login(request):
    from django.contrib.auth import authenticate, login as auth_login
    if request.method == 'POST':
        form = LoginForm(request.POST)
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if form.is_valid():
                auth_login(request, user)
                return redirect('home')
            else:
                messages.error(request, 'Please accept the privacy policy.')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    return render(request, 'tracker/login.html', {'form': form})


def contact_us(request):
    if request.user.is_authenticated and request.user.is_staff:
        messages.info(request, 'Admin messages are available from the dashboard inbox.')
        return redirect('admin_dashboard')

    recipient_email = _sandbox_contact_email()

    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            email = form.cleaned_data['email']
            subject = (form.cleaned_data['subject'] or 'General Inquiry').strip()
            message = form.cleaned_data['message']
            full_message = f"From: {name} ({email})\nSubject: {subject}\n\n{message}"
            contact_message = ContactMessage(
                user=request.user if request.user.is_authenticated else None,
                sender_name=name,
                sender_email=email,
                recipient_email=recipient_email,
                subject=subject,
                message_body=message,
            )
            try:
                email_message = EmailMessage(
                    subject=f'Habit Tracker Contact: {subject}',
                    body=full_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[recipient_email],
                    reply_to=[email],
                    headers={
                        'X-HabitTracker-Contact-Name': name,
                        'X-HabitTracker-Contact-Email': email,
                        'X-HabitTracker-Contact-Recipient': recipient_email,
                    },
                )
                email_message.send(fail_silently=False)
                contact_message.delivery_status = 'sent'
                contact_message.sent_at = timezone.now()
                contact_message.save()
                messages.success(request, 'Thank you for contacting us! We will respond soon.')
                return redirect('contact_us')
            except Exception as exc:
                contact_message.delivery_status = 'failed'
                contact_message.delivery_error = str(exc)
                contact_message.save()
                messages.error(request, 'We could not send your message right now. Please try again shortly.')
    else:
        initial = {}
        if request.user.is_authenticated:
            initial['name'] = request.user.get_full_name().strip() or request.user.username
            initial['email'] = request.user.email
        form = ContactForm(initial=initial)
    return render(
        request,
        'tracker/contact_us.html',
        {
            'form': form,
            'contact_recipient_email': recipient_email,
        },
    )


def home(request):
    if not request.user.is_authenticated:
        return redirect('login')

    today = timezone.localdate()
    week_start, week_end = week_bounds(today)
    week_dates = [week_start + datetime.timedelta(days=index) for index in range(7)]
    month_start, month_end = month_bounds(today)
    calendar_start = month_start - datetime.timedelta(days=month_start.weekday())
    calendar_end = month_end + datetime.timedelta(days=(6 - month_end.weekday()))

    habits = list(
        Habit.objects.filter(user=request.user)
        .prefetch_related(
            Prefetch('entries', queryset=HabitEntry.objects.order_by('date')),
            Prefetch('weekly_reviews', queryset=WeeklyReview.objects.order_by('-week_end')),
        )
        .order_by('-is_active', 'created_at')
    )

    entries_by_date = defaultdict(list)
    reviews_by_day = defaultdict(list)
    entry_maps = {}
    habit_chart_data = []
    week_completion_by_day = []
    today_completed_count = 0
    total_small_wins_this_week = 0
    best_consistency_streak = 0

    for habit in habits:
        prefetched_entries = list(habit.entries.all())
        entry_map = {entry.date: entry for entry in prefetched_entries}
        entry_maps[habit.id] = entry_map
        week_entries = [entry_map.get(day) for day in week_dates]
        weekly_total = round(sum(entry.quantity for entry in week_entries if entry), 2)
        completed_days = sum(1 for entry in week_entries if entry and entry.completed)
        progress_percent = round(min(100, (weekly_total / habit.weekly_target) * 100), 1) if habit.weekly_target else 0
        latest_review = next(iter(habit.weekly_reviews.all()), None)
        current_week_review = next(
            (review for review in habit.weekly_reviews.all() if review.week_start == week_start and review.week_end == week_end),
            None,
        )
        today_entry = entry_map.get(today)

        if today_entry and today_entry.completed:
            today_completed_count += 1

        for entry in prefetched_entries:
            if calendar_start <= entry.date <= calendar_end:
                entries_by_date[entry.date].append(entry)

        for review in habit.weekly_reviews.all():
            covered_days = (review.week_end - review.week_start).days + 1
            for offset in range(covered_days):
                review_day = review.week_start + datetime.timedelta(days=offset)
                reviews_by_day[review_day].append(review)

        habit.today_entry = today_entry
        habit.latest_review = latest_review
        habit.current_week_review = current_week_review
        habit.weekly_total = weekly_total
        habit.completed_days = completed_days
        habit.progress_percent = progress_percent
        habit.streak_count = compute_streak(entry_map, today)
        habit.weekly_average = round(weekly_total / max(1, len([entry for entry in week_entries if entry])), 2)
        habit.atomic_metrics = _habit_atomic_metrics(habit, prefetched_entries, today)
        habit.atomic_show_up_streak = habit.atomic_metrics['current_streak']
        habit.atomic_best_streak = habit.atomic_metrics['best_streak']
        habit.atomic_small_wins = habit.atomic_metrics['small_wins']
        habit.atomic_consistency_rate = habit.atomic_metrics['consistency_rate']
        habit.atomic_days = habit.atomic_metrics['days']
        habit.atomic_window_label = habit.atomic_metrics['window_label']
        habit.week_small_wins = sum(1 for day in week_dates if day in habit.atomic_metrics['small_win_dates'])
        habit.completion_quote = None
        if current_week_review:
            habit.review_prompt = (
                current_week_review.lessons
                or current_week_review.what_went_well
                or current_week_review.what_didnt
                or "Capture what helped, what resisted, and how you want to adjust next week."
            )
        else:
            habit.review_prompt = "Capture what helped, what resisted, and how you want to adjust next week."
        if today_entry and today_entry.completed:
            habit.completion_quote = COMPLETION_QUOTES[(habit.id + completed_days) % len(COMPLETION_QUOTES)]

        total_small_wins_this_week += habit.week_small_wins
        best_consistency_streak = max(best_consistency_streak, habit.atomic_best_streak)

        habit_chart_data.append(
            {
                'id': habit.id,
                'labels': [day.strftime('%b %d') for day in habit.atomic_metrics['window_dates']],
                'values': habit.atomic_metrics['quantity_series'],
                'target': habit.target_value,
                'color': habit.color,
                'unit': habit.unit,
                'smallWins': habit.atomic_metrics['small_win_series'],
                'streaks': habit.atomic_metrics['streak_series'],
            }
        )

    for day in week_dates:
        day_entries = entries_by_date.get(day, [])
        week_completion_by_day.append(sum(1 for entry in day_entries if entry.completed))

    calendar_days = []
    day_cursor = calendar_start
    while day_cursor <= calendar_end:
        day_entries = entries_by_date.get(day_cursor, [])
        calendar_days.append(
            {
                'date': day_cursor,
                'completed': sum(1 for entry in day_entries if entry.completed),
                'total': len(day_entries),
                'has_reviews': bool(reviews_by_day.get(day_cursor)),
                'is_current_month': day_cursor.month == month_start.month,
                'is_today': day_cursor == today,
            }
        )
        day_cursor += datetime.timedelta(days=1)

    calendar_weeks = [calendar_days[i:i+7] for i in range(0, len(calendar_days), 7)]

    current_week_reviews = sum(
        1
        for habit in habits
        if getattr(habit, 'current_week_review', None)
        and (
            habit.current_week_review.what_went_well
            or habit.current_week_review.what_didnt
            or habit.current_week_review.lessons
        )
    )
    today_completion_rate = round((today_completed_count / max(1, len(habits))) * 100, 1) if habits else 0
    week_overview_chart = {
        'labels': [day.strftime('%a') for day in week_dates],
        'completed': week_completion_by_day,
        'planned': [len(habits)] * len(week_dates),
    }
    pattern_atlas = _build_pattern_atlas(habits, entry_maps, set(reviews_by_day.keys()), today)

    context = {
        'habits': habits,
        'quotes': CAROUSEL_QUOTES,
        'calendar_days': calendar_days,
        'calendar_weeks': calendar_weeks,
        'week_dates': week_dates,
        'week_start': week_start,
        'week_end': week_end,
        'month_start': month_start,
        'month_end': month_end,
        'weekday_headers': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'habit_chart_data': habit_chart_data,
        'week_overview_chart': week_overview_chart,
        'dashboard_stats': {
            'habit_count': len(habits),
            'completed_today': today_completed_count,
            'weekly_reviews': current_week_reviews,
            'today_completion_rate': today_completion_rate,
            'small_wins_this_week': total_small_wins_this_week,
            'best_streak': best_consistency_streak,
        },
        'atomic_window_label': f'Last {ATOMIC_WINDOW_DAYS} days',
        'pattern_atlas': pattern_atlas,
        'overview_score_chart': pattern_atlas['score_chart'],
        'completion_history_chart': pattern_atlas['history_chart'],
    }
    return render(request, 'tracker/home.html', context)


def _habit_for_user(user, habit_id):
    return get_object_or_404(Habit.objects.select_related('user'), pk=habit_id, user=user)


def _week_chart_data(habit, week_dates, entry_map):
    small_win_dates = {day for day in week_dates if _entry_counts_as_small_win(entry_map.get(day))}
    return {
        'labels': [day.strftime('%a') for day in week_dates],
        'values': [entry_map.get(day).quantity if entry_map.get(day) else 0 for day in week_dates],
        'target': habit.target_value,
        'color': habit.color,
        'smallWins': [1 if day in small_win_dates else 0 for day in week_dates],
        'streaks': _streak_series(small_win_dates, week_dates),
    }


def _display_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.username


def _wallet_preview(address):
    if not address:
        return 'Not set'
    if len(address) <= 22:
        return address
    return f'{address[:12]}...{address[-8:]}'


def _format_amount(amount, currency=''):
    if amount is None:
        amount = Decimal('0')
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    formatted = f'{amount:.2f}'
    return f'{formatted} {currency}'.strip()


def _serialize_admin_user_row(user):
    profile = getattr(user, 'profile', None)
    user.dashboard_profile = profile
    user.full_name_display = user.get_full_name().strip() or 'No name set'
    user.theme_label = profile.get_theme_display() if profile else 'No profile'
    user.font_label = profile.get_font_display() if profile else 'No profile'
    user.gender_display = (profile.gender or '').title() if profile and profile.gender else 'Not set'
    user.age_display = profile.age if profile and profile.age is not None else 'Not set'
    user.mpesa_phone_display = profile.mpesa_phone if profile and profile.mpesa_phone else 'Not set'
    user.bitcoin_address_preview = _wallet_preview(profile.bitcoin_address if profile else '')
    user.primary_color = profile.primary_color if profile else '#ff7a59'
    user.secondary_color = profile.secondary_color if profile else '#3256ff'
    user.has_mpesa_phone = bool(profile and profile.mpesa_phone)
    user.has_bitcoin_address = bool(profile and profile.bitcoin_address)
    return user


def _admin_navigation(section):
    return [
        {
            'key': 'overview',
            'label': 'Overview',
            'icon': 'fa-solid fa-chart-pie',
            'url': reverse('admin_dashboard'),
        },
        {
            'key': 'users',
            'label': 'Users',
            'icon': 'fa-solid fa-users',
            'url': reverse('admin_users'),
        },
        {
            'key': 'habits',
            'label': 'Habits',
            'icon': 'fa-solid fa-list-check',
            'url': reverse('admin_habits'),
        },
        {
            'key': 'donations',
            'label': 'Donations',
            'icon': 'fa-solid fa-hand-holding-dollar',
            'url': reverse('admin_donations'),
        },
        {
            'key': 'messages',
            'label': 'Messages',
            'icon': 'fa-solid fa-envelope-open-text',
            'url': reverse('admin_messages'),
        },
    ]


def _admin_page_context(section, title, subtitle, **extra):
    context = {
        'admin_section': section,
        'admin_page_title': title,
        'admin_page_subtitle': subtitle,
        'admin_nav_items': _admin_navigation(section),
    }
    context.update(extra)
    return context


def _send_workspace_email(admin_email):
    reply_to = []
    if admin_email.sent_by and (admin_email.sent_by.email or '').strip():
        reply_to.append(admin_email.sent_by.email.strip())

    outbound_message = EmailMessage(
        subject=admin_email.subject,
        body=admin_email.message_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[admin_email.recipient_email],
        reply_to=reply_to or None,
        headers={
            'X-HabitTracker-Admin-Email': str(admin_email.pk),
            'X-HabitTracker-Admin-Sender': admin_email.sent_by.username if admin_email.sent_by else 'staff',
        },
    )
    outbound_message.send(fail_silently=False)


def _save_profile_form(profile_form, profile):
    for field_name in profile_form.fields:
        if field_name in profile_form.cleaned_data:
            setattr(profile, field_name, profile_form.cleaned_data[field_name])
    profile.save()


def _admin_user_directory(search_query='', role_filter='all', activity_filter='all', limit=None):
    role_options = [
        {'value': 'all', 'label': 'All accounts'},
        {'value': 'staff', 'label': 'Staff only'},
        {'value': 'members', 'label': 'Members only'},
        {'value': 'inactive', 'label': 'Inactive only'},
    ]
    activity_options = [
        {'value': 'all', 'label': 'All activity'},
        {'value': 'with_habits', 'label': 'Has habits'},
        {'value': 'without_habits', 'label': 'No habits yet'},
        {'value': 'with_donations', 'label': 'Has donations'},
        {'value': 'never_logged_in', 'label': 'Never logged in'},
    ]
    role_labels = {option['value']: option['label'] for option in role_options}
    activity_labels = {option['value']: option['label'] for option in activity_options}

    users_qs = (
        User.objects.select_related('profile')
        .annotate(
            habit_count=Count('habits', distinct=True),
            active_habit_count=Count('habits', filter=Q(habits__is_active=True), distinct=True),
            entry_count=Count('habits__entries', distinct=True),
            review_count=Count('habits__weekly_reviews', distinct=True),
            donation_count=Count('donations', distinct=True),
            completed_donation_count=Count('donations', filter=Q(donations__status='completed'), distinct=True),
            last_entry_date=Max('habits__entries__date'),
            last_review_date=Max('habits__weekly_reviews__week_end'),
            last_donation_at=Max('donations__created_at'),
        )
        .order_by('username')
    )

    if search_query:
        users_qs = users_qs.filter(
            Q(username__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(profile__mpesa_phone__icontains=search_query)
            | Q(profile__bitcoin_address__icontains=search_query)
        )

    if role_filter == 'staff':
        users_qs = users_qs.filter(is_staff=True)
    elif role_filter == 'members':
        users_qs = users_qs.filter(is_staff=False)
    elif role_filter == 'inactive':
        users_qs = users_qs.filter(is_active=False)

    if activity_filter == 'with_habits':
        users_qs = users_qs.filter(habit_count__gt=0)
    elif activity_filter == 'without_habits':
        users_qs = users_qs.filter(habit_count=0)
    elif activity_filter == 'with_donations':
        users_qs = users_qs.filter(donation_count__gt=0)
    elif activity_filter == 'never_logged_in':
        users_qs = users_qs.filter(last_login__isnull=True)

    users = [_serialize_admin_user_row(user) for user in users_qs]
    visible_users = len(users)
    if limit is not None:
        users = users[:limit]

    return {
        'users': users,
        'visible_user_count': visible_users,
        'role_options': role_options,
        'activity_options': activity_options,
        'selected_role_label': role_labels.get(role_filter, 'All accounts'),
        'selected_activity_label': activity_labels.get(activity_filter, 'All activity'),
        'search_query': search_query,
        'role_filter': role_filter,
        'activity_filter': activity_filter,
    }


def _admin_habit_directory(search_query='', status_filter='all', unit_filter='all', user_filter='all', limit=None):
    status_options = [
        {'value': 'all', 'label': 'All habits'},
        {'value': 'active', 'label': 'Active only'},
        {'value': 'paused', 'label': 'Paused only'},
    ]
    unit_options = [{'value': 'all', 'label': 'All units'}] + [
        {'value': value, 'label': label} for value, label in Habit.UNIT_CHOICES
    ]
    user_options = [{'value': 'all', 'label': 'All members'}] + [
        {'value': str(user.id), 'label': user.username} for user in User.objects.order_by('username')
    ]

    habits_qs = (
        Habit.objects.select_related('user')
        .annotate(
            entry_count=Count('entries', distinct=True),
            review_count=Count('weekly_reviews', distinct=True),
            last_entry_date=Max('entries__date'),
        )
        .order_by('-created_at')
    )

    if search_query:
        habits_qs = habits_qs.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(area__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
        )

    if status_filter == 'active':
        habits_qs = habits_qs.filter(is_active=True)
    elif status_filter == 'paused':
        habits_qs = habits_qs.filter(is_active=False)

    if unit_filter != 'all':
        habits_qs = habits_qs.filter(unit=unit_filter)

    if user_filter != 'all':
        habits_qs = habits_qs.filter(user_id=user_filter)

    habits = list(habits_qs)
    visible_habits = len(habits)
    if limit is not None:
        habits = habits[:limit]

    return {
        'habits': habits,
        'visible_habit_count': visible_habits,
        'habit_search_query': search_query,
        'habit_status_filter': status_filter,
        'habit_unit_filter': unit_filter,
        'habit_user_filter': str(user_filter),
        'habit_status_options': status_options,
        'habit_unit_options': unit_options,
        'habit_user_options': user_options,
    }


def _admin_donation_directory(search_query='', status_filter='all', method_filter='all', user_filter='all', limit=None):
    status_options = [{'value': 'all', 'label': 'All statuses'}] + [
        {'value': value, 'label': label} for value, label in Donation.STATUS_CHOICES
    ]
    method_options = [{'value': 'all', 'label': 'All methods'}] + [
        {'value': value, 'label': label} for value, label in Donation.METHOD_CHOICES
    ]
    user_options = [{'value': 'all', 'label': 'All members'}] + [
        {'value': str(user.id), 'label': user.username} for user in User.objects.order_by('username')
    ]

    donations_qs = Donation.objects.select_related('user').order_by('-created_at')

    if search_query:
        donations_qs = donations_qs.filter(
            Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(transaction_id__icontains=search_query)
            | Q(phone_number__icontains=search_query)
            | Q(wallet_address__icontains=search_query)
            | Q(status_message__icontains=search_query)
        )

    if status_filter != 'all':
        donations_qs = donations_qs.filter(status=status_filter)

    if method_filter != 'all':
        donations_qs = donations_qs.filter(method=method_filter)

    if user_filter != 'all':
        donations_qs = donations_qs.filter(user_id=user_filter)

    donations = list(donations_qs)
    visible_donations = len(donations)
    if limit is not None:
        donations = donations[:limit]

    return {
        'donations': donations,
        'visible_donation_count': visible_donations,
        'donation_search_query': search_query,
        'donation_status_filter': status_filter,
        'donation_method_filter': method_filter,
        'donation_user_filter': str(user_filter),
        'donation_status_options': status_options,
        'donation_method_options': method_options,
        'donation_user_options': user_options,
    }


def _admin_contact_directory(search_query='', status_filter='all', limit=None):
    status_options = [{'value': 'all', 'label': 'All statuses'}] + [
        {'value': value, 'label': label} for value, label in ContactMessage.DELIVERY_STATUS_CHOICES
    ]
    messages_qs = ContactMessage.objects.select_related('user').order_by('-created_at')

    if search_query:
        messages_qs = messages_qs.filter(
            Q(sender_name__icontains=search_query)
            | Q(sender_email__icontains=search_query)
            | Q(subject__icontains=search_query)
            | Q(message_body__icontains=search_query)
            | Q(recipient_email__icontains=search_query)
        )

    if status_filter != 'all':
        messages_qs = messages_qs.filter(delivery_status=status_filter)

    contact_messages = list(messages_qs)
    visible_messages = len(contact_messages)
    if limit is not None:
        contact_messages = contact_messages[:limit]

    return {
        'contact_messages': contact_messages,
        'visible_message_count': visible_messages,
        'message_search_query': search_query,
        'message_status_filter': status_filter,
        'message_status_options': status_options,
    }


@staff_member_required
def admin_dashboard(request):
    today = timezone.localdate()
    week_start, week_end = week_bounds(today)
    compose_initial = {}
    selected_compose_user = None
    compose_user_id = request.GET.get('compose_user', '').strip()
    if compose_user_id.isdigit():
        selected_compose_user = User.objects.filter(pk=compose_user_id).first()
        if selected_compose_user:
            compose_initial['recipient_user'] = selected_compose_user.pk

    if request.method == 'POST':
        admin_email_form = AdminEmailComposeForm(request.POST)
        if admin_email_form.is_valid():
            recipient_user = admin_email_form.cleaned_data['recipient_user']
            admin_email = AdminEmail.objects.create(
                sent_by=request.user,
                recipient_user=recipient_user,
                recipient_name=_display_name(recipient_user),
                recipient_email=recipient_user.email,
                subject=admin_email_form.cleaned_data['subject'],
                message_body=admin_email_form.cleaned_data['message_body'],
            )
            try:
                _send_workspace_email(admin_email)
                admin_email.delivery_status = 'sent'
                admin_email.sent_at = timezone.now()
                admin_email.delivery_error = ''
                admin_email.save(update_fields=['delivery_status', 'sent_at', 'delivery_error'])
                messages.success(request, f'Email sent to {recipient_user.username}.')
                return redirect(f"{reverse('admin_dashboard')}#admin-email-composer")
            except Exception as exc:
                admin_email.delivery_status = 'failed'
                admin_email.delivery_error = str(exc)
                admin_email.save(update_fields=['delivery_status', 'delivery_error'])
                messages.error(request, f'We could not send the email to {recipient_user.username} right now.')
    else:
        admin_email_form = AdminEmailComposeForm(initial=compose_initial)

    user_directory = _admin_user_directory(limit=6)
    habit_directory = _admin_habit_directory(limit=6)
    donation_directory = _admin_donation_directory(limit=6)
    contact_directory = _admin_contact_directory()
    recent_admin_emails = list(AdminEmail.objects.select_related('recipient_user', 'sent_by')[:6])
    total_users = User.objects.count()
    stats = {
        'user_count': total_users,
        'visible_users': user_directory['visible_user_count'],
        'staff_users': User.objects.filter(is_staff=True).count(),
        'inactive_users': User.objects.filter(is_active=False).count(),
        'logged_in_users': User.objects.exclude(last_login__isnull=True).count(),
        'users_never_logged_in': User.objects.filter(last_login__isnull=True).count(),
        'users_without_habits': User.objects.annotate(habit_count=Count('habits')).filter(habit_count=0).count(),
        'users_with_donations': User.objects.annotate(donation_count=Count('donations')).filter(donation_count__gt=0).count(),
    }

    completed_donation_total = Donation.objects.filter(status='completed').aggregate(total=Sum('amount'))['total']
    system_stats = {
        'habit_count': Habit.objects.count(),
        'active_habits': Habit.objects.filter(is_active=True).count(),
        'entries_today': HabitEntry.objects.filter(date=today).count(),
        'reviews_this_week': WeeklyReview.objects.filter(week_start=week_start, week_end=week_end).count(),
        'completed_donations_total': _format_amount(completed_donation_total),
    }

    donation_breakdown = []
    donation_chart_labels = []
    donation_chart_counts = []
    for method_value, method_label in Donation.METHOD_CHOICES:
        method_qs = Donation.objects.filter(method=method_value)
        total_count = method_qs.count()
        completed_amount = method_qs.filter(status='completed').aggregate(total=Sum('amount'))['total']
        currency = method_qs.exclude(currency='').values_list('currency', flat=True).first() or ''
        donation_breakdown.append(
            {
                'label': method_label,
                'total_count': total_count,
                'total_amount': _format_amount(completed_amount, currency),
            }
        )
        donation_chart_labels.append(method_label)
        donation_chart_counts.append(total_count)

    stats_chart = {
        'labels': donation_chart_labels,
        'counts': donation_chart_counts,
    }
    top_users = sorted(
        _admin_user_directory()['users'],
        key=lambda user_row: (
            user_row.entry_count,
            user_row.review_count,
            user_row.habit_count,
            user_row.donation_count,
        ),
        reverse=True,
    )[:5]

    context = _admin_page_context(
        'overview',
        'Admin Workspace',
        'Monitor members, tracking activity, donations, and the sandbox Gmail inbox from one responsive workspace.',
        stats=stats,
        system_stats=system_stats,
        today=today,
        donation_breakdown=donation_breakdown,
        stats_chart=stats_chart,
        top_users=top_users,
        contact_recipient_email=_sandbox_contact_email(),
        email_delivery_status=_contact_email_delivery_context(),
        contact_message_stats={
            'total': ContactMessage.objects.count(),
            'sent': ContactMessage.objects.filter(delivery_status='sent').count(),
            'failed': ContactMessage.objects.filter(delivery_status='failed').count(),
        },
        admin_email_stats={
            'total': AdminEmail.objects.count(),
            'sent': AdminEmail.objects.filter(delivery_status='sent').count(),
            'failed': AdminEmail.objects.filter(delivery_status='failed').count(),
        },
        admin_email_form=admin_email_form,
        preview_admin_emails=recent_admin_emails,
        selected_compose_user=selected_compose_user,
        preview_users=user_directory['users'],
        preview_habits=habit_directory['habits'],
        preview_donations=donation_directory['donations'],
        preview_messages=contact_directory['contact_messages'],
    )
    return render(request, 'tracker/admin_dashboard.html', context)


@staff_member_required
def admin_users(request):
    directory = _admin_user_directory(
        search_query=request.GET.get('user_q', '').strip(),
        role_filter=request.GET.get('user_role', 'all').strip() or 'all',
        activity_filter=request.GET.get('user_activity', 'all').strip() or 'all',
    )
    context = _admin_page_context(
        'users',
        'User Management',
        'Create accounts, adjust staff access, and edit profile settings without opening Django admin.',
        **directory,
    )
    return render(request, 'tracker/admin_users.html', context)


@staff_member_required
def admin_user_create(request):
    if request.method == 'POST':
        user_form = AdminUserCreateForm(request.POST)
        profile_form = AdminProfileForm(request.POST, request.FILES)
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()
            _save_profile_form(profile_form, user.profile)
            messages.success(request, f'User {user.username} was created.')
            return redirect('admin_users')
    else:
        user_form = AdminUserCreateForm(initial={'is_active': True})
        profile_form = AdminProfileForm()

    context = _admin_page_context(
        'users',
        'Create User',
        'Add a member or staff account and configure its profile preferences in one save.',
        form=user_form,
        secondary_form=profile_form,
        primary_form_title='Account details',
        secondary_form_title='Profile settings',
        submit_label='Create user',
        cancel_url=reverse('admin_users'),
        form_action='multipart/form-data',
    )
    return render(request, 'tracker/admin_form.html', context)


@staff_member_required
def admin_user_edit(request, user_id):
    managed_user = get_object_or_404(User.objects.select_related('profile'), pk=user_id)

    if request.method == 'POST':
        user_form = AdminUserChangeForm(request.POST, instance=managed_user)
        profile_form = AdminProfileForm(request.POST, request.FILES, instance=managed_user.profile)
        if user_form.is_valid() and profile_form.is_valid():
            updated_user = user_form.save()
            profile_form.save()
            if updated_user == request.user and user_form.cleaned_data.get('new_password'):
                update_session_auth_hash(request, updated_user)
            messages.success(request, f'User {updated_user.username} was updated.')
            return redirect('admin_users')
    else:
        user_form = AdminUserChangeForm(instance=managed_user)
        profile_form = AdminProfileForm(instance=managed_user.profile)

    context = _admin_page_context(
        'users',
        f'Edit {managed_user.username}',
        'Review account permissions, profile preferences, and saved payment details.',
        form=user_form,
        secondary_form=profile_form,
        primary_form_title='Account details',
        secondary_form_title='Profile settings',
        submit_label='Save changes',
        cancel_url=reverse('admin_users'),
        form_action='multipart/form-data',
        record_summary=f'{managed_user.username} · {managed_user.email or "No email"}',
    )
    return render(request, 'tracker/admin_form.html', context)


@staff_member_required
def admin_user_delete(request, user_id):
    managed_user = get_object_or_404(User, pk=user_id)
    if managed_user == request.user:
        messages.error(request, 'Use another staff account if you need to remove this user.')
        return redirect('admin_users')

    if request.method == 'POST':
        username = managed_user.username
        managed_user.delete()
        messages.success(request, f'User {username} was deleted.')
        return redirect('admin_users')

    context = _admin_page_context(
        'users',
        'Delete User',
        'This removes the account and all related profile, habit, and review records.',
        object_label=managed_user.username,
        object_meta=managed_user.email or 'No email set',
        cancel_url=reverse('admin_users'),
        delete_label='Delete user',
    )
    return render(request, 'tracker/admin_confirm_delete.html', context)


@staff_member_required
def admin_habits(request):
    directory = _admin_habit_directory(
        search_query=request.GET.get('habit_q', '').strip(),
        status_filter=request.GET.get('habit_status', 'all').strip() or 'all',
        unit_filter=request.GET.get('habit_unit', 'all').strip() or 'all',
        user_filter=request.GET.get('habit_user', 'all').strip() or 'all',
    )
    context = _admin_page_context(
        'habits',
        'Habit Library',
        'Filter and manage every tracked habit, including owner assignment and active status.',
        **directory,
    )
    return render(request, 'tracker/admin_habits.html', context)


@staff_member_required
def admin_habit_create(request):
    if request.method == 'POST':
        form = AdminHabitForm(request.POST)
        if form.is_valid():
            habit = form.save()
            messages.success(request, f'Habit {habit.title} was created.')
            return redirect('admin_habits')
    else:
        form = AdminHabitForm(initial={'is_active': True, 'start_date': timezone.localdate()})

    context = _admin_page_context(
        'habits',
        'Create Habit',
        'Add a new habit directly for any member.',
        form=form,
        primary_form_title='Habit details',
        submit_label='Create habit',
        cancel_url=reverse('admin_habits'),
    )
    return render(request, 'tracker/admin_form.html', context)


@staff_member_required
def admin_habit_edit(request, habit_id):
    habit = get_object_or_404(Habit.objects.select_related('user'), pk=habit_id)
    if request.method == 'POST':
        form = AdminHabitForm(request.POST, instance=habit)
        if form.is_valid():
            habit = form.save()
            messages.success(request, f'Habit {habit.title} was updated.')
            return redirect('admin_habits')
    else:
        form = AdminHabitForm(instance=habit)

    context = _admin_page_context(
        'habits',
        f'Edit {habit.title}',
        'Update cadence, targets, reminders, and ownership.',
        form=form,
        primary_form_title='Habit details',
        submit_label='Save changes',
        cancel_url=reverse('admin_habits'),
        record_summary=f'{habit.user.username} · {habit.get_unit_display()} target',
    )
    return render(request, 'tracker/admin_form.html', context)


@staff_member_required
def admin_habit_delete(request, habit_id):
    habit = get_object_or_404(Habit.objects.select_related('user'), pk=habit_id)
    if request.method == 'POST':
        title = habit.title
        habit.delete()
        messages.success(request, f'Habit {title} was deleted.')
        return redirect('admin_habits')

    context = _admin_page_context(
        'habits',
        'Delete Habit',
        'This removes the habit and all of its entries and weekly reviews.',
        object_label=habit.title,
        object_meta=f'Owned by {habit.user.username}',
        cancel_url=reverse('admin_habits'),
        delete_label='Delete habit',
    )
    return render(request, 'tracker/admin_confirm_delete.html', context)


@staff_member_required
def admin_donations(request):
    directory = _admin_donation_directory(
        search_query=request.GET.get('donation_q', '').strip(),
        status_filter=request.GET.get('donation_status', 'all').strip() or 'all',
        method_filter=request.GET.get('donation_method', 'all').strip() or 'all',
        user_filter=request.GET.get('donation_user', 'all').strip() or 'all',
    )
    context = _admin_page_context(
        'donations',
        'Donation Tracking',
        'Review payment states, references, and manual adjustments in one place.',
        **directory,
    )
    return render(request, 'tracker/admin_donations.html', context)


@staff_member_required
def admin_donation_create(request):
    if request.method == 'POST':
        form = AdminDonationForm(request.POST)
        if form.is_valid():
            donation = form.save()
            messages.success(request, 'Donation record created.')
            return redirect('admin_donations')
    else:
        form = AdminDonationForm(initial={'currency': 'KES', 'status': 'pending'})

    context = _admin_page_context(
        'donations',
        'Create Donation Record',
        'Manually capture or correct donation records while keeping payment tracking intact.',
        form=form,
        primary_form_title='Donation details',
        submit_label='Create donation',
        cancel_url=reverse('admin_donations'),
    )
    return render(request, 'tracker/admin_form.html', context)


@staff_member_required
def admin_donation_edit(request, donation_id):
    donation = get_object_or_404(Donation.objects.select_related('user'), pk=donation_id)
    if request.method == 'POST':
        form = AdminDonationForm(request.POST, instance=donation)
        if form.is_valid():
            form.save()
            messages.success(request, 'Donation record updated.')
            return redirect('admin_donations')
    else:
        form = AdminDonationForm(instance=donation)

    context = _admin_page_context(
        'donations',
        'Edit Donation',
        'Update payment references, status, or stored payload details.',
        form=form,
        primary_form_title='Donation details',
        submit_label='Save changes',
        cancel_url=reverse('admin_donations'),
        record_summary=f'{donation.amount} {donation.currency} · {donation.get_status_display()}',
    )
    return render(request, 'tracker/admin_form.html', context)


@staff_member_required
def admin_donation_delete(request, donation_id):
    donation = get_object_or_404(Donation, pk=donation_id)
    if request.method == 'POST':
        donation.delete()
        messages.success(request, 'Donation record deleted.')
        return redirect('admin_donations')

    context = _admin_page_context(
        'donations',
        'Delete Donation',
        'Only remove a payment record when it is incorrect or duplicated.',
        object_label=f'{donation.amount} {donation.currency}',
        object_meta=donation.transaction_id or donation.get_method_display(),
        cancel_url=reverse('admin_donations'),
        delete_label='Delete donation',
    )
    return render(request, 'tracker/admin_confirm_delete.html', context)


@staff_member_required
def admin_messages(request):
    directory = _admin_contact_directory(
        search_query=request.GET.get('message_q', '').strip(),
        status_filter=request.GET.get('message_status', 'all').strip() or 'all',
    )
    context = _admin_page_context(
        'messages',
        'Communications Workspace',
        'Review user emails delivered to the sandbox inbox and monitor staff outreach without leaving the workspace.',
        contact_recipient_email=_sandbox_contact_email(),
        email_delivery_status=_contact_email_delivery_context(),
        admin_email_stats={
            'total': AdminEmail.objects.count(),
            'sent': AdminEmail.objects.filter(delivery_status='sent').count(),
            'failed': AdminEmail.objects.filter(delivery_status='failed').count(),
        },
        sent_admin_emails=AdminEmail.objects.select_related('recipient_user', 'sent_by')[:20],
        **directory,
    )
    return render(request, 'tracker/admin_messages.html', context)


@staff_member_required
def admin_message_detail(request, message_id):
    contact_message = get_object_or_404(ContactMessage.objects.select_related('user'), pk=message_id)
    context = _admin_page_context(
        'messages',
        'Inbox Message',
        'Review the full sender details and message body exactly as captured from the public contact flow.',
        contact_message=contact_message,
        contact_recipient_email=_sandbox_contact_email(),
        email_delivery_status=_contact_email_delivery_context(),
    )
    return render(request, 'tracker/admin_message_detail.html', context)


@staff_member_required
def admin_message_create(request):
    messages.info(request, 'Inbox messages are system-generated from user submissions, so there is no admin message form here.')
    return redirect('admin_messages')


@staff_member_required
def admin_message_edit(request, message_id):
    messages.info(request, 'Inbox messages are read-only in the workspace. Review the message details instead.')
    return redirect('admin_message_detail', message_id=message_id)


@staff_member_required
def admin_message_delete(request, message_id):
    contact_message = get_object_or_404(ContactMessage, pk=message_id)
    if request.method == 'POST':
        contact_message.delete()
        messages.success(request, 'Contact message deleted.')
        return redirect('admin_messages')

    context = _admin_page_context(
        'messages',
        'Delete Message',
        'Only remove a contact message when it is spam, duplicated, or invalid.',
        object_label=contact_message.subject or 'General Inquiry',
        object_meta=contact_message.sender_email,
        cancel_url=reverse('admin_messages'),
        delete_label='Delete message',
    )
    return render(request, 'tracker/admin_confirm_delete.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, 'Your account is ready. Welcome to Habit Tracker.')
            return redirect('home')
    else:
        form = SignUpForm()

    return render(request, 'tracker/signup.html', {'form': form})


@login_required(login_url='login')
def profile(request):
    profile_instance = request.user.profile

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile_instance)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('profile')
    else:
        form = ProfileForm(instance=profile_instance)

    habits = Habit.objects.filter(user=request.user)
    entries = HabitEntry.objects.filter(habit__user=request.user)
    completed_entries = entries.filter(completed=True)
    donations = Donation.objects.filter(user=request.user).order_by('-created_at')
    stats = {
        'habit_count': habits.count(),
        'entry_count': entries.count(),
        'completion_rate': round((completed_entries.count() / max(1, entries.count())) * 100, 1),
        'donation_total': donations.filter(status='completed').count(),
    }
    context = {
        'form': form,
        'stats': stats,
        'recent_reviews': WeeklyReview.objects.filter(habit__user=request.user).select_related('habit').order_by('-week_end')[:5],
        'donations': donations[:8],
    }
    return render(request, 'tracker/profile.html', context)


@login_required(login_url='login')
def create_habit(request):
    if request.method == 'POST':
        form = HabitForm(request.POST)
        if form.is_valid():
            habit = form.save(commit=False)
            habit.user = request.user
            habit.save()
            messages.success(request, 'Habit created. Your Atomic Habit blueprint is ready.')
            return redirect('home')
    else:
        form = HabitForm()

    return render(request, 'tracker/habit_form.html', {'form': form, 'title': 'Create Habit'})


@login_required(login_url='login')
def edit_habit(request, habit_id):
    habit = _habit_for_user(request.user, habit_id)

    if request.method == 'POST':
        form = HabitForm(request.POST, instance=habit)
        if form.is_valid():
            form.save()
            messages.success(request, 'Habit updated. Your Atomic Habit blueprint has been refreshed.')
            return redirect('home')
    else:
        form = HabitForm(instance=habit)

    return render(request, 'tracker/habit_form.html', {'form': form, 'title': 'Edit Habit'})


@login_required(login_url='login')
def delete_habit(request, habit_id):
    habit = _habit_for_user(request.user, habit_id)

    if request.method == 'POST':
        habit.delete()
        messages.success(request, 'Habit deleted.')
        return redirect('home')

    return render(request, 'tracker/confirm_delete.html', {'object': habit})


@login_required(login_url='login')
def habit_entry(request, habit_id):
    habit = _habit_for_user(request.user, habit_id)
    default_date = request.GET.get('date') or timezone.localdate().isoformat()
    try:
        entry_date = datetime.date.fromisoformat(default_date)
    except ValueError:
        entry_date = timezone.localdate()

    existing_entry = HabitEntry.objects.filter(habit=habit, date=entry_date).first()

    if request.method == 'POST':
        submitted_date = request.POST.get('date') or timezone.localdate().isoformat()
        try:
            submitted_entry_date = datetime.date.fromisoformat(submitted_date)
        except ValueError:
            submitted_entry_date = timezone.localdate()
        existing_entry = HabitEntry.objects.filter(habit=habit, date=submitted_entry_date).first()
        form = HabitEntryForm(request.POST, instance=existing_entry)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.habit = habit
            duplicate = HabitEntry.objects.filter(habit=habit, date=entry.date).exclude(pk=entry.pk).first()
            if duplicate:
                duplicate.quantity = entry.quantity
                duplicate.completed = entry.completed
                duplicate.note = entry.note
                duplicate.save()
            else:
                entry.save()
            messages.success(request, 'Entry saved.')
            return redirect('home')
    else:
        form = HabitEntryForm(
            instance=existing_entry,
            initial={'date': entry_date, 'quantity': habit.target_value},
        )

    context = {
        'form': form,
        'habit': habit,
        'recent_entries': habit.entries.order_by('-date')[:7],
        'atomic_metrics': _habit_atomic_metrics(habit, list(habit.entries.order_by('date')), timezone.localdate()),
    }
    return render(request, 'tracker/habit_entry.html', context)


@login_required(login_url='login')
def weekly_review(request, habit_id):
    habit = _habit_for_user(request.user, habit_id)
    today = timezone.localdate()
    week_start, week_end = week_bounds(today)
    week_dates = [week_start + datetime.timedelta(days=index) for index in range(7)]
    entry_map = {
        entry.date: entry
        for entry in habit.entries.filter(date__range=(week_start, week_end))
    }
    existing_review = WeeklyReview.objects.filter(habit=habit, week_start=week_start, week_end=week_end).first()

    if request.method == 'POST':
        form = WeeklyReviewForm(request.POST, request.FILES, instance=existing_review)
        if form.is_valid():
            review = form.save(commit=False)
            review.habit = habit
            review.week_start = week_start
            review.week_end = week_end
            review.save()
            messages.success(request, 'Weekly review saved.')
            return redirect('home')
    else:
        form = WeeklyReviewForm(instance=existing_review)

    weekly_entries = list(entry_map.values())
    weekly_total = round(sum(entry.quantity for entry in weekly_entries), 2)
    completed_days = sum(1 for entry in weekly_entries if entry.completed)
    atomic_metrics = _habit_atomic_metrics(habit, list(habit.entries.filter(date__lte=today).order_by('date')), today)
    context = {
        'form': form,
        'habit': habit,
        'week_start': week_start,
        'week_end': week_end,
        'weekly_total': weekly_total,
        'completed_days': completed_days,
        'small_wins_this_week': sum(1 for day in week_dates if day in atomic_metrics['small_win_dates']),
        'atomic_metrics': atomic_metrics,
        'target_total': habit.weekly_target,
        'previous_reviews': habit.weekly_reviews.exclude(pk=existing_review.pk if existing_review else None).order_by('-week_end')[:6],
        'chart_data': _week_chart_data(habit, week_dates, entry_map),
    }
    return render(request, 'tracker/weekly_review.html', context)


@login_required(login_url='login')
def calendar_events(request):
    events = []
    entries = HabitEntry.objects.filter(habit__user=request.user).select_related('habit').order_by('date', 'habit__title')
    for entry in entries:
        title = f'{entry.habit.title}: {entry.quantity:g} {entry.habit.unit}'
        if entry.completed:
            title = f'{entry.habit.title}: completed'
        events.append(
            {
                'title': title,
                'start': entry.date.isoformat(),
                'url': reverse('calendar_day', kwargs={'date_str': entry.date.isoformat()}),
                'backgroundColor': entry.habit.color,
                'borderColor': entry.habit.color,
            }
        )

    reviews = WeeklyReview.objects.filter(habit__user=request.user).select_related('habit')
    for review in reviews:
        events.append(
            {
                'title': f'{review.habit.title}: weekly review',
                'start': review.week_end.isoformat(),
                'url': reverse('calendar_day', kwargs={'date_str': review.week_end.isoformat()}),
                'backgroundColor': '#172033',
                'borderColor': '#172033',
            }
        )

    return JsonResponse(events, safe=False)


@login_required(login_url='login')
def calendar_day(request, date_str):
    try:
        day = datetime.date.fromisoformat(date_str)
    except ValueError:
        messages.error(request, 'That calendar date is not valid.')
        return redirect('home')

    entries = HabitEntry.objects.filter(habit__user=request.user, date=day).select_related('habit').order_by('habit__title')
    reviews = (
        WeeklyReview.objects.filter(habit__user=request.user, week_start__lte=day, week_end__gte=day)
        .select_related('habit')
        .order_by('-week_end', 'habit__title')
    )
    context = {
        'day': day,
        'entries': entries,
        'reviews': reviews,
        'summary': {
            'completed_count': sum(1 for entry in entries if entry.completed),
            'total_entries': len(entries),
            'review_count': len(reviews),
        },
    }
    return render(request, 'tracker/calendar_day.html', context)


@csrf_exempt
def mpesa_callback(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed.'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON payload.'}, status=400)

    callback_details = extract_stk_callback_details(payload)
    checkout_request_id = callback_details.get('checkout_request_id')
    donation = Donation.objects.filter(transaction_id=checkout_request_id).order_by('-created_at').first()

    if not donation:
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Callback received.'})

    metadata = callback_details.get('metadata', {})
    receipt_number = metadata.get('MpesaReceiptNumber')
    phone_number = metadata.get('PhoneNumber')
    result_code = callback_details.get('result_code')
    result_desc = callback_details.get('result_desc') or 'Callback received.'

    if phone_number:
        donation.phone_number = str(phone_number)

    donation.payment_payload = merge_payment_payload(
        donation.payment_payload,
        merchant_request_id=callback_details.get('merchant_request_id'),
        checkout_request_id=checkout_request_id,
        result_code=result_code,
        result_desc=result_desc,
        mpesa_receipt_number=receipt_number,
        phone_number=str(phone_number) if phone_number else donation.phone_number,
    )

    if result_code == 0:
        donation.status = 'completed'
        receipt_message = f' Receipt: {receipt_number}.' if receipt_number else ''
        donation.status_message = f'{result_desc}{receipt_message}'
    else:
        donation.status = 'failed'
        donation.status_message = result_desc

    donation.save()
    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@login_required(login_url='login')
def donate(request):
    addresses = load_electrum_addresses()
    default_btc = getattr(settings, 'BITCOIN_WALLET_ADDRESS', '').strip() or (addresses[0] if addresses else '')
    mpesa_config_issues = daraja_configuration_errors()
    donation_result = None
    latest_mpesa_phone = None
    latest_mpesa_reference = None
    qr_uri = generate_qr_data_uri(default_btc) if default_btc else None
    qr_title = 'Bitcoin wallet QR'
    qr_caption = 'default BTC wallet QR'

    if request.method == 'POST':
        form = DonationForm(request.POST)
        if form.is_valid():
            donation = form.save(commit=False)
            donation.user = request.user

            if donation.method == 'mpesa':
                try:
                    response_payload = initiate_mpesa_stk_push(
                        donation.phone_number,
                        donation.amount,
                        request.user.username,
                        'Habit Tracker donation',
                    )
                    donation.transaction_id = response_payload.get('CheckoutRequestID')
                    donation.status = 'pending'
                    donation.status_message = (
                        f"{response_payload.get('CustomerMessage', 'STK push sent.')} "
                        f"CheckoutRequestID: {donation.transaction_id}."
                    ).strip()
                    donation.payment_payload = merge_payment_payload(
                        donation.payment_payload,
                        checkout_request_id=donation.transaction_id,
                        response_code=response_payload.get('ResponseCode'),
                        customer_message=response_payload.get('CustomerMessage'),
                        phone_number=donation.phone_number,
                    )
                    donation.save()
                    donation_result = donation.status_message
                    latest_mpesa_phone = donation.phone_number
                    latest_mpesa_reference = donation.transaction_id
                    messages.success(request, 'M-Pesa request sent.')
                except DarajaError as exc:
                    donation.status = 'failed'
                    donation.status_message = str(exc)
                    donation.payment_payload = merge_payment_payload(
                        donation.payment_payload,
                        phone_number=donation.phone_number,
                    )
                    donation.save()
                    donation_result = donation.status_message
                    latest_mpesa_phone = donation.phone_number
                    messages.error(request, donation.status_message)
            elif donation.method == 'bitcoin':
                donation.status = 'pending'
                donation.wallet_address = donation.wallet_address or default_btc
                donation.status_message = 'Bitcoin donation request saved. Send funds to the selected wallet.'
                donation.save()
                qr_uri = generate_qr_data_uri(donation.wallet_address)
                qr_title = 'Bitcoin wallet QR'
                qr_caption = 'Scan to open the selected Bitcoin wallet address.'
                donation_result = donation.status_message
                messages.success(request, 'Bitcoin donation details saved.')
            else:
                donation.status = 'pending'
                donation.status_message = 'Lightning invoice saved. Complete payment from your wallet app.'
                donation.save()
                qr_uri = generate_qr_data_uri(donation.lightning_invoice)
                qr_title = 'Lightning invoice QR'
                qr_caption = 'Scan to pay the pasted Lightning invoice.'
                donation_result = donation.status_message
                messages.success(request, 'Lightning invoice saved.')
        else:
            donation_result = 'Please correct the form and try again.'
    else:
        form = DonationForm(
            initial={
                'currency': 'KES',
                'wallet_address': default_btc,
            }
        )

    context = {
        'form': form,
        'addresses': addresses,
        'default_btc': default_btc,
        'mpesa_ready': daraja_is_configured(),
        'mpesa_config_issues': mpesa_config_issues,
        'mpesa_callback_url': getattr(settings, 'MPESA_CALLBACK_URL', ''),
        'donation_result': donation_result,
        'latest_mpesa_phone': latest_mpesa_phone,
        'latest_mpesa_reference': latest_mpesa_reference,
        'qr_uri': qr_uri,
        'qr_title': qr_title,
        'qr_caption': qr_caption,
    }
    return render(request, 'tracker/donate.html', context)


@login_required(login_url='login')
def export_data(request):
    export_format = request.GET.get('format', 'txt').lower()
    habits = Habit.objects.filter(user=request.user).order_by('title')
    entries = HabitEntry.objects.filter(habit__user=request.user).select_related('habit').order_by('date', 'habit__title')
    reviews = WeeklyReview.objects.filter(habit__user=request.user).select_related('habit').order_by('-week_end', 'habit__title')
    donations = Donation.objects.filter(user=request.user).order_by('-created_at')

    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="habit-tracker-export.csv"'
        writer = csv.writer(response)
        writer.writerow([f'Habit Tracker Report for {request.user.username}'])
        writer.writerow([])
        writer.writerow(['Habit Entries'])
        writer.writerow(['Habit', 'Date', 'Quantity', 'Completed', 'Note'])
        for entry in entries:
            writer.writerow([entry.habit.title, entry.date.isoformat(), entry.quantity, entry.completed, entry.note])
        writer.writerow([])
        writer.writerow(['Weekly Reviews'])
        writer.writerow(['Habit', 'Week Start', 'Week End', 'What Went Well', 'Challenges', 'Lessons'])
        for review in reviews:
            writer.writerow([
                review.habit.title,
                review.week_start.isoformat(),
                review.week_end.isoformat(),
                review.what_went_well,
                review.what_didnt,
                review.lessons,
            ])
        writer.writerow([])
        writer.writerow(['Donations'])
        writer.writerow(['Method', 'Amount', 'Currency', 'Status', 'Reference'])
        for donation in donations:
            writer.writerow([
                donation.get_method_display(),
                donation.amount,
                donation.currency,
                donation.status,
                donation.transaction_id or donation.wallet_address or donation.phone_number or '',
            ])
        return response

    response = HttpResponse(content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="habit-tracker-report.txt"'

    lines = [
        f'Habit Tracker Report for {request.user.username}',
        '',
        'Habits',
    ]
    for habit in habits:
        lines.append(f'- {habit.title}: {habit.description or "No description"}')

    lines.extend(['', 'Habit Entries'])
    for entry in entries:
        lines.append(
            f'- {entry.date.isoformat()} | {entry.habit.title} | {entry.quantity} {entry.habit.unit} | '
            f'{"Done" if entry.completed else "Open"} | {entry.note or "No note"}'
        )

    lines.extend(['', 'Weekly Reviews'])
    for review in reviews:
        lines.append(f'- {review.habit.title} ({review.week_start.isoformat()} to {review.week_end.isoformat()})')
        lines.append(f'  Went well: {review.what_went_well or "Nothing recorded."}')
        lines.append(f'  Challenges: {review.what_didnt or "Nothing recorded."}')
        lines.append(f'  Lessons: {review.lessons or "Nothing recorded."}')

    lines.extend(['', 'Donations'])
    for donation in donations:
        lines.append(
            f'- {donation.created_at:%Y-%m-%d} | {donation.get_method_display()} | '
            f'{donation.amount} {donation.currency} | {donation.status.title()}'
        )

    response.write('\n'.join(lines))
    return response


def privacy_policy(request):
    return render(request, 'tracker/privacy_policy.html')
