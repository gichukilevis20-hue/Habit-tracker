from django.contrib import admin

from .models import ContactMessage, Donation, Habit, HabitEntry, Profile, WeeklyReview


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'gender', 'age', 'theme', 'font', 'mpesa_phone')
    list_filter = ('theme', 'font', 'gender')
    search_fields = ('user__username', 'user__email', 'mpesa_phone', 'bitcoin_address')


@admin.register(Habit)
class HabitAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'unit', 'target_value', 'is_active', 'created_at')
    list_filter = ('unit', 'is_active', 'created_at')
    search_fields = ('title', 'user__username', 'description', 'identity_statement', 'tiny_step', 'habit_stack_cue', 'consistency_plan')
    list_select_related = ('user',)


@admin.register(HabitEntry)
class HabitEntryAdmin(admin.ModelAdmin):
    list_display = ('habit', 'date', 'quantity', 'completed')
    list_filter = ('completed', 'date', 'habit__unit')
    search_fields = ('habit__title', 'habit__user__username', 'note')
    autocomplete_fields = ('habit',)


@admin.register(WeeklyReview)
class WeeklyReviewAdmin(admin.ModelAdmin):
    list_display = ('habit', 'week_start', 'week_end', 'created_at')
    list_filter = ('week_start', 'week_end', 'created_at')
    search_fields = ('habit__title', 'habit__user__username', 'what_went_well', 'lessons')
    autocomplete_fields = ('habit',)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ('user', 'method', 'amount', 'currency', 'status', 'transaction_id', 'created_at')
    list_filter = ('method', 'status', 'currency', 'created_at')
    search_fields = ('user__username', 'transaction_id', 'phone_number', 'wallet_address')
    list_select_related = ('user',)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('sender_name', 'sender_email', 'recipient_email', 'subject', 'delivery_status', 'created_at')
    list_filter = ('delivery_status', 'created_at')
    search_fields = ('sender_name', 'sender_email', 'subject', 'message_body')
    list_select_related = ('user',)


admin.site.site_header = 'Habit Tracker Administration'
admin.site.site_title = 'Habit Tracker Admin'
admin.site.index_title = 'Project overview'
