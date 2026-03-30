from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.dateparse import parse_date

from tracker.models import HabitEntry
from tracker.reminders import build_missed_habit_reminders, build_personalized_reminder_email

class Command(BaseCommand):
    help = 'Send personalized habit reminders for missed habits and weekly review alerts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            dest='run_date',
            help='Process reminders for a specific day in YYYY-MM-DD format.',
        )

    def handle(self, *args, **options):
        run_date = options.get('run_date')
        today = parse_date(run_date) if run_date else timezone.localdate()
        if run_date and today is None:
            raise CommandError('Invalid --date value. Use YYYY-MM-DD.')

        users = User.objects.all()
        personalized_count = 0
        weekly_review_count = 0
        weekly_goal_count = 0

        for user in users:
            if not user.email:
                continue

            habits = list(user.habits.filter(is_active=True).order_by('title'))
            if not habits:
                continue

            entry_map = {
                entry.habit_id: entry
                for entry in HabitEntry.objects.filter(habit__in=habits, date=today)
            }
            missed_habits = build_missed_habit_reminders(habits, entry_map, today)

            if missed_habits:
                subject, message = build_personalized_reminder_email(user, missed_habits, today)
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
                    personalized_count += 1
                except Exception as exc:
                    self.stderr.write(f'Failed to send personalized reminder to {user.email}: {exc}')

            if today.weekday() == 6:
                subject = 'Weekly Review Reminder'
                message = (
                    f"Hi {user.username},\n\n"
                    "It is time to write your weekly habit reviews. Visit your dashboard to share insights and lessons learned."
                )
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
                    weekly_review_count += 1
                except Exception as exc:
                    self.stderr.write(f'Failed to send weekly review reminder to {user.email}: {exc}')

            if today.weekday() == 0:
                subject = 'Weekly Goals Reminder'
                message = (
                    f"Hi {user.username},\n\n"
                    "A new week has started. Review your active habits and set the tone for your upcoming goals."
                )
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
                    weekly_goal_count += 1
                except Exception as exc:
                    self.stderr.write(f'Failed to send weekly goals reminder to {user.email}: {exc}')

        self.stdout.write(
            self.style.SUCCESS(
                f'Reminders processed for {today.isoformat()}: '
                f'{personalized_count} personalized, '
                f'{weekly_review_count} weekly review, '
                f'{weekly_goal_count} weekly goal.'
            )
        )
