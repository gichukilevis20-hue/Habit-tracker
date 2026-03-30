from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

class Profile(models.Model):
    FONT_CHOICES = [
        ('default', 'Manrope'),
        ('montserrat', 'Montserrat'),
        ('space_grotesk', 'Space Grotesk'),
        ('playfair', 'Playfair Display'),
        ('merriweather', 'Merriweather'),
        ('courier', 'Courier New'),
    ]
    THEME_CHOICES = [
        ('colorful', 'Colorful'),
        ('minimal', 'Minimal'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    gender = models.CharField(max_length=16, blank=True, null=True)
    age = models.PositiveIntegerField(blank=True, null=True)
    profile_image = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    oauth_profile_source = models.CharField(max_length=32, blank=True, default='')
    oauth_profile_image_url = models.URLField(blank=True, default='')
    oauth_profile_synced_at = models.DateTimeField(blank=True, null=True)
    theme = models.CharField(max_length=16, choices=THEME_CHOICES, default='colorful')
    font = models.CharField(max_length=32, choices=FONT_CHOICES, default='default')
    primary_color = models.CharField(max_length=7, default='#ff7a59')
    secondary_color = models.CharField(max_length=7, default='#3256ff')
    mpesa_phone = models.CharField(max_length=20, blank=True, null=True)
    bitcoin_address = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} profile"

    @property
    def profile_image_url(self):
        if self.profile_image and self.profile_image.name:
            try:
                return self.profile_image.url
            except ValueError:
                return None
        if self.oauth_profile_image_url:
            return self.oauth_profile_image_url
        return None

class Habit(models.Model):
    UNIT_CHOICES = [
        ('hours', 'Hours'),
        ('km', 'Kilometers'),
        ('reps', 'Repetitions'),
        ('money', 'Money'),
        ('times', 'Times'),
        ('boolean', 'Yes/No'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='habits')
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    identity_statement = models.TextField(blank=True, default='')
    tiny_step = models.TextField(blank=True, default='')
    habit_stack_cue = models.TextField(blank=True, default='')
    consistency_plan = models.TextField(blank=True, default='')
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='times')
    target_value = models.FloatField(default=1.0)
    repeat = models.CharField(max_length=20, choices=[('daily','Daily'),('weekly','Weekly'),('monthly','Monthly')], default='daily')
    every_n_days = models.PositiveSmallIntegerField(default=1)
    time_of_day = models.CharField(max_length=64, blank=True, default='Morning,Afternoon,Evening')
    start_date = models.DateField(default=timezone.localdate)
    end_condition = models.CharField(max_length=64, blank=True, default='Never')
    reminders = models.CharField(max_length=128, blank=True, default='')
    area = models.CharField(max_length=64, blank=True, default='General')
    color = models.CharField(max_length=7, default='#ff7a59')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

    @property
    def weekly_progress(self):
        start = timezone.localdate() - timedelta(days=6)
        entries = self.entries.filter(date__gte=start)
        total = sum(e.quantity for e in entries)
        return total

    @property
    def completion_rate(self):
        start = timezone.localdate() - timedelta(days=6)
        days = 7
        completed = self.entries.filter(date__gte=start, completed=True).count()
        return round((completed / days) * 100, 1)

    @property
    def weekly_target(self):
        return round(self.target_value * 7, 2)

    @property
    def streak(self):
        today = timezone.localdate()
        recent_entries = {
            entry.date: entry
            for entry in self.entries.filter(date__lte=today).order_by('-date')
        }
        streak = 0
        cursor = today
        while cursor in recent_entries and recent_entries[cursor].completed:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    @property
    def target_label(self):
        return f"{self.target_value:g} {self.get_unit_display().lower()}"

    @property
    def identity_focus(self):
        identity = (self.identity_statement or '').strip()
        return identity or 'I am the kind of person who keeps showing up for this habit.'

    @property
    def tiny_step_focus(self):
        tiny_step = (self.tiny_step or '').strip()
        return tiny_step or 'Do the smallest version of this habit today and let showing up count as progress.'

    @property
    def stack_focus(self):
        habit_stack_cue = (self.habit_stack_cue or '').strip()
        return habit_stack_cue or 'Attach this habit to something you already do every day so the cue stays obvious.'

    @property
    def consistency_focus(self):
        consistency_plan = (self.consistency_plan or '').strip()
        return consistency_plan or 'Protect the next repetition and keep the schedule simple enough to repeat.'

class HabitEntry(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name='entries')
    date = models.DateField()
    quantity = models.FloatField(default=0)
    completed = models.BooleanField(default=False)
    note = models.TextField(blank=True)

    class Meta:
        unique_together = ('habit', 'date')

    def __str__(self):
        return f"{self.habit.title} on {self.date}" 

class WeeklyReview(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name='weekly_reviews')
    week_start = models.DateField()
    week_end = models.DateField()
    what_went_well = models.TextField(blank=True)
    what_didnt = models.TextField(blank=True)
    lessons = models.TextField(blank=True)
    photo = models.ImageField(upload_to='review_photos/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('habit', 'week_start', 'week_end')

    def __str__(self):
        return f"Review for {self.habit.title} week {self.week_start}" 

class Donation(models.Model):
    METHOD_CHOICES = [
        ('mpesa', 'M-Pesa (Daraja)'),
        ('bitcoin', 'Bitcoin'),
        ('bitcoin_lightning', 'Bitcoin Lightning'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='donations')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='KES')
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    wallet_address = models.CharField(max_length=128, blank=True, null=True)
    transaction_id = models.CharField(max_length=128, blank=True, null=True)
    lightning_invoice = models.TextField(blank=True, null=True)
    payment_payload = models.TextField(blank=True, null=True)
    status_message = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.method} {self.amount} {self.currency} ({self.status})"


class ContactMessage(models.Model):
    DELIVERY_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='contact_messages')
    sender_name = models.CharField(max_length=100)
    sender_email = models.EmailField()
    recipient_email = models.EmailField(default='habittracker001@gmail.com')
    subject = models.CharField(max_length=200, blank=True, default='General Inquiry')
    message_body = models.TextField()
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='pending')
    delivery_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.sender_email} -> {self.recipient_email} ({self.subject or 'General Inquiry'})"


class AdminEmail(models.Model):
    DELIVERY_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    sent_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='workspace_sent_emails',
    )
    recipient_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='workspace_received_emails',
    )
    recipient_name = models.CharField(max_length=150)
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=200)
    message_body = models.TextField()
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='pending')
    delivery_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.subject} -> {self.recipient_email}"

