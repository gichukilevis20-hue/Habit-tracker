import calendar
from dataclasses import dataclass

from django.conf import settings
from django.template.loader import render_to_string


DEFAULT_REASON = "You started this habit because it supports the life you want to build."


@dataclass(frozen=True)
class MissedHabitReminder:
    title: str
    goal_summary: str
    reason: str
    repeat_label: str


def get_user_display_name(user):
    full_name = user.get_full_name().strip()
    return full_name or user.first_name or user.username


def format_value(value):
    return f"{value:g}"


def goal_summary_for_habit(habit):
    if habit.unit == 'boolean':
        if habit.repeat == 'daily':
            return 'Check it off each day to protect your weekly rhythm.'
        if habit.repeat == 'weekly':
            return 'Check it off once each week.'
        return 'Check it off once each month.'

    unit_label = habit.get_unit_display().lower()
    target_value = format_value(habit.target_value)

    if habit.repeat == 'daily':
        weekly_target = format_value(habit.weekly_target)
        return f"{target_value} {unit_label} each day ({weekly_target} {unit_label} this week)."
    if habit.repeat == 'weekly':
        return f"{target_value} {unit_label} each week."
    if habit.repeat == 'monthly':
        return f"{target_value} {unit_label} each month."
    return f"{target_value} {unit_label} on each scheduled check-in."


def reason_for_habit(habit):
    description = (habit.description or '').strip()
    return description or DEFAULT_REASON


def months_between(start_date, target_date):
    return ((target_date.year - start_date.year) * 12) + (target_date.month - start_date.month)


def is_habit_due_on(habit, day):
    if not habit.is_active or day < habit.start_date:
        return False

    interval = max(1, habit.every_n_days or 1)

    if habit.repeat == 'daily':
        elapsed_days = (day - habit.start_date).days
        return elapsed_days % interval == 0

    if habit.repeat == 'weekly':
        elapsed_days = (day - habit.start_date).days
        elapsed_weeks = elapsed_days // 7
        return day.weekday() == habit.start_date.weekday() and elapsed_weeks % interval == 0

    if habit.repeat == 'monthly':
        elapsed_months = months_between(habit.start_date, day)
        if elapsed_months < 0 or elapsed_months % interval != 0:
            return False
        month_last_day = calendar.monthrange(day.year, day.month)[1]
        target_day = min(habit.start_date.day, month_last_day)
        return day.day == target_day

    return True


def build_missed_habit_reminders(habits, entry_map, day):
    reminders = []
    for habit in habits:
        if not is_habit_due_on(habit, day):
            continue

        entry = entry_map.get(habit.id)
        if entry and entry.completed:
            continue

        reminders.append(
            MissedHabitReminder(
                title=habit.title,
                goal_summary=goal_summary_for_habit(habit),
                reason=reason_for_habit(habit),
                repeat_label=habit.get_repeat_display(),
            )
        )

    return reminders


def build_personalized_reminder_email(user, missed_habits, day):
    app_name = getattr(settings, 'APP_NAME', 'Habit Tracker')
    subject = (
        f"{app_name}: remember why {missed_habits[0].title} matters"
        if len(missed_habits) == 1
        else f"{app_name}: your daily reset for {len(missed_habits)} habits"
    )
    message = render_to_string(
        'tracker/emails/daily_habit_reminder.txt',
        {
            'app_name': app_name,
            'day': day,
            'display_name': get_user_display_name(user),
            'missed_habits': missed_habits,
            'motivation_line': (
                'A small step tomorrow is enough to restart momentum.'
                if len(missed_habits) == 1
                else 'You do not need to fix everything tomorrow. Start with the easiest win and rebuild the rhythm.'
            ),
        },
    ).strip()
    return subject, message
