import datetime
import json
import os
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .context_processors import app_shell
from .forms import normalize_phone_number
from .models import AdminEmail, ContactMessage, Donation, Habit, HabitEntry, WeeklyReview
from .payments import DarajaError, daraja_configuration_errors
from .social_profiles import build_fake_sociallogin, supplement_user_from_social_profile


class SignUpFlowTests(TestCase):
    def test_signup_creates_profile_and_logs_user_in(self):
        response = self.client.post(
            reverse('signup'),
            {
                'username': 'newuser',
                'email': 'newuser@example.com',
                'password1': 'ComplexPass123!',
                'password2': 'ComplexPass123!',
                'gender': 'female',
                'age': 29,
            },
        )

        self.assertRedirects(response, reverse('home'))
        user = User.objects.get(username='newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertEqual(user.profile.gender, 'female')
        self.assertEqual(user.profile.age, 29)


class AuthenticationFlowTests(TestCase):
    def test_logout_redirects_back_to_login_page(self):
        user = User.objects.create_user(username='june', password='TestPass123!')
        self.client.login(username='june', password='TestPass123!')

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))


class SocialLoginTests(TestCase):
    @override_settings(
        SOCIAL_LOGIN_ENABLED=True,
        SOCIALACCOUNT_PROVIDERS={
            'google': {
                'APPS': [{'client_id': 'google-client-id', 'secret': 'google-secret', 'key': ''}],
            },
            'github': {
                'APPS': [],
            },
        }
    )
    def test_anonymous_context_lists_all_social_providers_and_marks_configuration_state(self):
        request = RequestFactory().get(reverse('login'))
        request.user = AnonymousUser()

        context = app_shell(request)
        providers = context['social_login_providers']

        self.assertEqual([provider['id'] for provider in providers], ['google', 'microsoft', 'github', 'facebook'])
        self.assertEqual(providers[0]['login_url'], '/accounts/google/login/')
        self.assertTrue(providers[0]['is_configured'])
        self.assertFalse(providers[1]['is_configured'])
        self.assertFalse(providers[2]['is_configured'])
        self.assertFalse(providers[3]['is_configured'])
        self.assertEqual(context['social_login_configured_count'], 1)
        self.assertEqual(context['social_login_unconfigured_count'], 3)

    @override_settings(
        SOCIAL_LOGIN_ENABLED=True,
        SOCIALACCOUNT_PROVIDERS={
            'google': {
                'APPS': [{'client_id': 'google-client-id', 'secret': 'google-secret', 'key': ''}],
            },
            'microsoft': {
                'APPS': [{'client_id': 'microsoft-client-id', 'secret': 'microsoft-secret', 'key': ''}],
            },
            'github': {
                'APPS': [{'client_id': 'github-client-id', 'secret': 'github-secret', 'key': ''}],
            },
            'facebook': {
                'APPS': [{'client_id': 'facebook-client-id', 'secret': 'facebook-secret', 'key': ''}],
            },
        }
    )
    def test_login_page_renders_all_configured_provider_buttons_as_secure_posts(self):
        response = self.client.get(reverse('login'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Continue with Google')
        self.assertContains(response, 'Continue with Microsoft')
        self.assertContains(response, 'Continue with GitHub')
        self.assertContains(response, 'Continue with Facebook')
        self.assertIn('method="post" action="/accounts/google/login/"', content)
        self.assertIn('method="post" action="/accounts/microsoft/login/"', content)
        self.assertIn('method="post" action="/accounts/github/login/"', content)
        self.assertIn('method="post" action="/accounts/facebook/login/"', content)
        self.assertContains(response, 'Social sign-in imports only basic profile details')

    @override_settings(
        SOCIAL_LOGIN_ENABLED=True,
        SOCIALACCOUNT_PROVIDERS={
            'google': {'APPS': []},
            'microsoft': {'APPS': []},
            'github': {'APPS': []},
            'facebook': {'APPS': []},
        }
    )
    def test_login_page_shows_unavailable_provider_buttons_when_credentials_are_missing(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Continue with Google')
        self.assertContains(response, 'Continue with Microsoft')
        self.assertContains(response, 'Continue with GitHub')
        self.assertContains(response, 'Continue with Facebook')
        self.assertContains(response, 'Setup needed')
        self.assertContains(response, 'still need server OAuth credentials before sign-in can start')


class SocialProfileSyncTests(TestCase):
    def test_supplement_user_from_social_profile_only_fills_blank_fields(self):
        user = User.objects.create_user(
            username='mira',
            password='TestPass123!',
            email='existing@example.com',
            first_name='Existing',
            last_name='Name',
        )
        profile = user.profile

        changed = supplement_user_from_social_profile(
            user,
            {
                'provider': 'google',
                'email': 'new@example.com',
                'first_name': 'New',
                'last_name': 'Person',
                'full_name': 'New Person',
                'avatar_url': 'https://images.example.com/avatar.png',
            },
            profile=profile,
        )

        user.refresh_from_db()
        profile.refresh_from_db()

        self.assertTrue(changed)
        self.assertEqual(user.email, 'existing@example.com')
        self.assertEqual(user.first_name, 'Existing')
        self.assertEqual(user.last_name, 'Name')
        self.assertEqual(profile.oauth_profile_source, 'google')
        self.assertEqual(profile.oauth_profile_image_url, 'https://images.example.com/avatar.png')
        self.assertIsNotNone(profile.oauth_profile_synced_at)

    def test_supplement_user_from_social_profile_prefers_uploaded_avatar_over_remote_avatar(self):
        user = User.objects.create_user(username='mira', password='TestPass123!')
        user.profile.profile_image = SimpleUploadedFile(
            'avatar.jpg',
            b'fake-image-bytes',
            content_type='image/jpeg',
        )
        user.profile.save()

        supplement_user_from_social_profile(
            user,
            {
                'provider': 'github',
                'email': 'mira@example.com',
                'first_name': 'Mira',
                'last_name': 'Stone',
                'full_name': 'Mira Stone',
                'avatar_url': 'https://avatars.example.com/github.png',
            },
            profile=user.profile,
        )

        user.refresh_from_db()
        profile = user.profile
        self.assertEqual(profile.oauth_profile_source, 'github')
        self.assertEqual(profile.oauth_profile_image_url, '')
        profile.profile_image.delete(save=False)

    def test_profile_page_displays_imported_social_avatar_when_no_uploaded_photo_exists(self):
        user = User.objects.create_user(username='mira', password='TestPass123!', email='mira@example.com')
        user.profile.oauth_profile_source = 'google'
        user.profile.oauth_profile_image_url = 'https://images.example.com/google-avatar.png'
        user.profile.save()
        self.client.login(username='mira', password='TestPass123!')

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'https://images.example.com/google-avatar.png')
        self.assertContains(response, 'Imported from your Google sign-in')

    def test_build_fake_sociallogin_exposes_provider_avatar_lookup(self):
        sociallogin = build_fake_sociallogin(
            'facebook',
            extra_data={
                'email': 'mira@example.com',
                'name': 'Mira Stone',
                'picture': {'data': {'url': 'https://graph.example.com/avatar.png'}},
            },
            avatar_url='https://graph.example.com/avatar.png',
        )

        self.assertEqual(sociallogin.account.provider, 'facebook')
        self.assertEqual(sociallogin.account.extra_data['email'], 'mira@example.com')
        self.assertEqual(sociallogin.account.get_avatar_url(), 'https://graph.example.com/avatar.png')


class ExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='mira', password='TestPass123!', email='mira@example.com')
        self.client.login(username='mira', password='TestPass123!')
        self.habit = Habit.objects.create(
            user=self.user,
            title='Read',
            description='Read every day',
            unit='hours',
            target_value=1,
        )
        HabitEntry.objects.create(habit=self.habit, date=timezone.localdate(), quantity=1.5, completed=True, note='Strong focus session')
        week_start = timezone.localdate() - datetime.timedelta(days=timezone.localdate().weekday())
        WeeklyReview.objects.create(
            habit=self.habit,
            week_start=week_start,
            week_end=week_start + datetime.timedelta(days=6),
            what_went_well='I stayed consistent.',
            what_didnt='Missed one evening.',
            lessons='Morning sessions work best.',
        )
        Donation.objects.create(
            user=self.user,
            method='bitcoin',
            amount=Decimal('5.00'),
            currency='BTC',
            status='pending',
            wallet_address='bc1testwallet',
            transaction_id='BTC-1',
        )

    def test_csv_export_contains_all_sections(self):
        response = self.client.get(reverse('export_data'), {'format': 'csv'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Habit Entries', content)
        self.assertIn('Weekly Reviews', content)
        self.assertIn('Donations', content)
        self.assertIn('Read', content)

    def test_text_export_contains_summary(self):
        response = self.client.get(reverse('export_data'), {'format': 'txt'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Habit Tracker Report for mira', content)
        self.assertIn('Morning sessions work best.', content)


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        self.client.login(username='adminuser', password='AdminPass123!')

    def test_staff_can_open_admin_dashboard(self):
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Workspace')
        self.assertContains(response, 'Open Users')
        self.assertContains(response, 'Open Habits')
        self.assertContains(response, 'Open Donations')
        self.assertContains(response, 'Open Inbox')

    def test_dashboard_previews_workspace_records(self):
        tracked_user = User.objects.create_user(
            username='kelly',
            password='TestPass123!',
            email='kelly@example.com',
            first_name='Kelly',
            last_name='Stone',
        )
        tracked_user.profile.theme = 'minimal'
        tracked_user.profile.font = 'space_grotesk'
        tracked_user.profile.gender = 'female'
        tracked_user.profile.age = 31
        tracked_user.profile.mpesa_phone = '254712345678'
        tracked_user.profile.bitcoin_address = 'bc1qexamplewallet1234567890'
        tracked_user.profile.save()
        habit = Habit.objects.create(user=tracked_user, title='Write', unit='times', target_value=1)
        HabitEntry.objects.create(habit=habit, date=timezone.localdate(), quantity=1, completed=True)
        Donation.objects.create(
            user=tracked_user,
            method='bitcoin',
            amount=Decimal('3.00'),
            currency='BTC',
            status='completed',
            wallet_address='bc1qexamplewallet1234567890',
            transaction_id='BTC-999',
        )
        ContactMessage.objects.create(
            user=tracked_user,
            sender_name='Kelly',
            sender_email='kelly@example.com',
            recipient_email='habittracker001@gmail.com',
            subject='Feature question',
            message_body='Can I customize reminder times?',
            delivery_status='sent',
        )

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent Directory Snapshot')
        self.assertContains(response, 'kelly')
        self.assertContains(response, 'kelly@example.com')
        self.assertContains(response, 'Newest Habits')
        self.assertContains(response, 'BTC-999')
        self.assertContains(response, 'Feature question')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admin_can_send_personalized_email_from_dashboard_and_monitor_it(self):
        tracked_user = User.objects.create_user(
            username='kelly',
            password='TestPass123!',
            email='kelly@example.com',
            first_name='Kelly',
        )

        response = self.client.post(
            reverse('admin_dashboard'),
            {
                'recipient_user': str(tracked_user.id),
                'subject': 'Weekly reset',
                'message_body': 'Kelly, your consistency is building. Keep the next check-in simple and repeatable.',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['kelly@example.com'])
        self.assertEqual(mail.outbox[0].reply_to, ['admin@example.com'])
        self.assertIn('Weekly reset', mail.outbox[0].subject)
        self.assertIn('Keep the next check-in simple and repeatable.', mail.outbox[0].body)

        admin_email = AdminEmail.objects.get(recipient_user=tracked_user)
        self.assertEqual(admin_email.delivery_status, 'sent')
        self.assertEqual(admin_email.sent_by, self.staff_user)
        self.assertContains(response, 'Email sent to kelly.')
        self.assertContains(response, 'Recent staff emails')
        self.assertContains(response, 'Weekly reset')

        communications_response = self.client.get(reverse('admin_messages'))
        self.assertEqual(communications_response.status_code, 200)
        self.assertContains(communications_response, 'Staff emails sent from the workspace')
        self.assertContains(communications_response, 'kelly@example.com')
        self.assertContains(communications_response, 'Weekly reset')

    def test_user_workspace_filters_directory(self):
        User.objects.create_user(username='alphauser', password='TestPass123!', email='alpha@example.com')
        User.objects.create_user(username='betauser', password='TestPass123!', email='beta@example.com')

        response = self.client.get(reverse('admin_users'), {'user_q': 'alphauser'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alphauser')
        self.assertContains(response, 'Search: "alphauser"')
        self.assertContains(response, '1 results')


class AdminWorkspaceCrudTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        self.member = User.objects.create_user(
            username='member1',
            password='TestPass123!',
            email='member1@example.com',
        )
        self.client.login(username='adminuser', password='AdminPass123!')

    def test_admin_can_create_user_with_profile_from_workspace(self):
        response = self.client.post(
            reverse('admin_user_create'),
            {
                'username': 'newmember',
                'email': 'newmember@example.com',
                'first_name': 'New',
                'last_name': 'Member',
                'is_active': 'on',
                'password1': 'ComplexPass123!',
                'password2': 'ComplexPass123!',
                'gender': 'female',
                'age': '28',
                'theme': 'minimal',
                'font': 'space_grotesk',
                'primary_color': '#112233',
                'secondary_color': '#445566',
                'mpesa_phone': '254712345678',
                'bitcoin_address': 'bc1qworkspacecreate1234567890',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created_user = User.objects.get(username='newmember')
        self.assertEqual(created_user.email, 'newmember@example.com')
        self.assertEqual(created_user.profile.theme, 'minimal')
        self.assertEqual(created_user.profile.font, 'space_grotesk')
        self.assertEqual(created_user.profile.mpesa_phone, '254712345678')
        self.assertContains(response, 'User newmember was created.')

    def test_admin_can_create_edit_and_delete_habit_from_workspace(self):
        create_response = self.client.post(
            reverse('admin_habit_create'),
            {
                'user': str(self.member.id),
                'title': 'Stretch',
                'description': 'Morning stretch routine',
                'unit': 'times',
                'target_value': '1',
                'repeat': 'daily',
                'every_n_days': '1',
                'time_of_day': 'Morning',
                'start_date': timezone.localdate().isoformat(),
                'end_condition': 'Never',
                'reminders': '08:00',
                'area': 'Health',
                'color': '#ff7a59',
                'is_active': 'on',
            },
            follow=True,
        )

        self.assertEqual(create_response.status_code, 200)
        habit = Habit.objects.get(title='Stretch')
        edit_response = self.client.post(
            reverse('admin_habit_edit', args=[habit.id]),
            {
                'user': str(self.member.id),
                'title': 'Stretch Daily',
                'description': 'Updated stretch routine',
                'unit': 'times',
                'target_value': '2',
                'repeat': 'daily',
                'every_n_days': '1',
                'time_of_day': 'Morning,Evening',
                'start_date': timezone.localdate().isoformat(),
                'end_condition': 'Never',
                'reminders': '08:00,18:00',
                'area': 'Health',
                'color': '#3256ff',
                'is_active': 'on',
            },
            follow=True,
        )

        habit.refresh_from_db()
        self.assertEqual(habit.title, 'Stretch Daily')
        self.assertEqual(habit.target_value, 2)
        self.assertContains(edit_response, 'Habit Stretch Daily was updated.')

        delete_response = self.client.post(reverse('admin_habit_delete', args=[habit.id]), follow=True)

        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(Habit.objects.filter(id=habit.id).exists())
        self.assertContains(delete_response, 'Habit Stretch Daily was deleted.')

    def test_admin_can_create_edit_and_delete_donation_record(self):
        create_response = self.client.post(
            reverse('admin_donation_create'),
            {
                'user': str(self.member.id),
                'method': 'mpesa',
                'amount': '250',
                'currency': 'KES',
                'phone_number': '0712345678',
                'wallet_address': '',
                'transaction_id': 'MANUAL-001',
                'lightning_invoice': '',
                'status': 'pending',
                'status_message': 'Awaiting confirmation',
                'payment_payload': '{"source": "admin"}',
            },
            follow=True,
        )

        self.assertEqual(create_response.status_code, 200)
        donation = Donation.objects.get(transaction_id='MANUAL-001')
        self.assertEqual(donation.phone_number, '254712345678')

        edit_response = self.client.post(
            reverse('admin_donation_edit', args=[donation.id]),
            {
                'user': str(self.member.id),
                'method': 'mpesa',
                'amount': '250',
                'currency': 'KES',
                'phone_number': '254712345678',
                'wallet_address': '',
                'transaction_id': 'MANUAL-001',
                'lightning_invoice': '',
                'status': 'completed',
                'status_message': 'Confirmed manually',
                'payment_payload': '{"source": "admin", "confirmed": true}',
            },
            follow=True,
        )

        donation.refresh_from_db()
        self.assertEqual(donation.status, 'completed')
        self.assertEqual(donation.status_message, 'Confirmed manually')
        self.assertContains(edit_response, 'Donation record updated.')

        delete_response = self.client.post(reverse('admin_donation_delete', args=[donation.id]), follow=True)

        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(Donation.objects.filter(id=donation.id).exists())
        self.assertContains(delete_response, 'Donation record deleted.')

    def test_admin_can_view_and_delete_contact_message_record(self):
        contact_message = ContactMessage.objects.create(
            user=self.member,
            sender_name='Member One',
            sender_email='member1@example.com',
            recipient_email='habittracker001@gmail.com',
            subject='Help needed',
            message_body='Please help with my reminders.',
            delivery_status='pending',
        )

        detail_response = self.client.get(reverse('admin_message_detail', args=[contact_message.id]))

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'Member One')
        self.assertContains(detail_response, 'member1@example.com')
        self.assertContains(detail_response, 'Please help with my reminders.')

        delete_response = self.client.post(reverse('admin_message_delete', args=[contact_message.id]), follow=True)

        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(ContactMessage.objects.filter(id=contact_message.id).exists())
        self.assertContains(delete_response, 'Contact message deleted.')


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CONTACT_RECIPIENT_EMAIL='habittracker001@gmail.com',
    DEFAULT_FROM_EMAIL='Habit Tracker <habittracker001@gmail.com>',
)
class ContactUsTests(TestCase):
    def test_contact_page_is_linked_from_public_navigation(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('contact_us'))

    def test_contact_form_sends_to_sandbox_inbox_and_stores_message(self):
        response = self.client.post(
            reverse('contact_us'),
            {
                'name': 'Levis',
                'email': 'levis@example.com',
                'subject': 'Need help',
                'message': 'The dashboard is not updating for me.',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.to, ['habittracker001@gmail.com'])
        self.assertEqual(sent_message.reply_to, ['levis@example.com'])
        self.assertIn('Need help', sent_message.subject)

        stored_message = ContactMessage.objects.get()
        self.assertEqual(stored_message.sender_name, 'Levis')
        self.assertEqual(stored_message.sender_email, 'levis@example.com')
        self.assertEqual(stored_message.recipient_email, 'habittracker001@gmail.com')
        self.assertEqual(stored_message.delivery_status, 'sent')
        self.assertEqual(stored_message.subject, 'Need help')
        self.assertEqual(stored_message.message_body, 'The dashboard is not updating for me.')

    @override_settings(CONTACT_RECIPIENT_EMAIL='wrong@example.com', SANDBOX_GMAIL_ADDRESS='habittracker001@gmail.com')
    def test_contact_form_always_targets_the_sandbox_gmail_account(self):
        self.client.post(
            reverse('contact_us'),
            {
                'name': 'Levis',
                'email': 'levis@example.com',
                'subject': 'Sandbox route',
                'message': 'Please route this to the sandbox inbox only.',
            },
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['habittracker001@gmail.com'])
        stored_message = ContactMessage.objects.get(subject='Sandbox route')
        self.assertEqual(stored_message.recipient_email, 'habittracker001@gmail.com')

    def test_staff_is_redirected_from_contact_form_to_admin_dashboard(self):
        staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        self.client.login(username='adminuser', password='AdminPass123!')

        response = self.client.get(reverse('contact_us'))

        self.assertRedirects(response, reverse('admin_dashboard'))

    def test_admin_dashboard_displays_all_contact_messages_without_admin_message_form_actions(self):
        staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        for index in range(7):
            ContactMessage.objects.create(
                sender_name=f'Kelly {index}',
                sender_email=f'kelly{index}@example.com',
                recipient_email='habittracker001@gmail.com',
                subject=f'Feature question {index}',
                message_body=f'Can I customize reminder times for message {index}?',
                delivery_status='sent',
            )

        self.client.login(username='adminuser', password='AdminPass123!')
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'All user emails routed to habittracker001@gmail.com')
        self.assertContains(response, 'kelly0@example.com')
        self.assertContains(response, 'Feature question 0')
        self.assertContains(response, 'Can I customize reminder times for message 0?')
        self.assertContains(response, 'Feature question 6')
        self.assertNotContains(response, 'Add Record')

    def test_admin_inbox_page_is_read_only_and_shows_full_message_details(self):
        staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        contact_message = ContactMessage.objects.create(
            sender_name='Kelly',
            sender_email='kelly@example.com',
            recipient_email='habittracker001@gmail.com',
            subject='Feature question',
            message_body='Can I customize reminder times?\nI need the full answer here.',
            delivery_status='sent',
        )

        self.client.login(username='adminuser', password='AdminPass123!')
        response = self.client.get(reverse('admin_messages'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sandbox Gmail Inbox')
        self.assertContains(response, 'kelly@example.com')
        self.assertContains(response, 'I need the full answer here.')
        self.assertContains(response, reverse('admin_message_detail', args=[contact_message.id]))
        self.assertNotContains(response, 'Add Record')


class DashboardPresentationTests(TestCase):
    def test_home_page_uses_habit_journey_welcome_copy_and_contact_call_to_action(self):
        user = User.objects.create_user(username='mira', password='TestPass123!', email='mira@example.com')
        self.client.login(username='mira', password='TestPass123!')

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome to Your Habit Journey')
        self.assertContains(response, reverse('contact_us'))

    def test_home_page_displays_pattern_atlas_sections_and_recent_month_labels(self):
        user = User.objects.create_user(username='mira', password='TestPass123!', email='mira@example.com')
        self.client.login(username='mira', password='TestPass123!')
        today = timezone.localdate()
        habit = Habit.objects.create(
            user=user,
            title='Read',
            description='Read every day',
            unit='times',
            target_value=1,
            repeat='daily',
            every_n_days=1,
            start_date=today - datetime.timedelta(days=40),
        )
        for offset in [0, 1, 2, 4, 8, 15]:
            HabitEntry.objects.create(
                habit=habit,
                date=today - datetime.timedelta(days=offset),
                quantity=1,
                completed=True,
            )

        response = self.client.get(reverse('home'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pattern atlas')
        self.assertContains(response, 'Seasonal completion calendar')
        self.assertContains(response, 'Top completion runs')
        self.assertContains(response, 'By day of the week')
        self.assertContains(response, 'Today to yearly progress')
        self.assertIn('overview-score-chart', content)
        self.assertIn('completion-history-chart', content)

        month_anchor = today.replace(day=1)
        for offset in range(-3, 1):
            month_index = (month_anchor.month - 1) + offset
            year = month_anchor.year + (month_index // 12)
            month = (month_index % 12) + 1
            self.assertContains(response, datetime.date(year, month, 1).strftime('%B %Y'))

    def test_staff_home_page_uses_workspace_links_instead_of_django_admin_links(self):
        staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        self.client.login(username='adminuser', password='AdminPass123!')

        response = self.client.get(reverse('home'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('admin_habits'))
        self.assertContains(response, reverse('admin_donations'))
        self.assertContains(response, '#admin-email-composer')
        self.assertNotIn('/admin/tracker/habit/', content)
        self.assertNotIn('/admin/tracker/donation/', content)
        self.assertNotIn('/admin/tracker/contactmessage/', content)

    def test_home_page_includes_mobile_calendar_hooks_for_small_screens(self):
        user = User.objects.create_user(username='nina', password='TestPass123!', email='nina@example.com')
        self.client.login(username='nina', password='TestPass123!')

        response = self.client.get(reverse('home'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn("matchMedia('(max-width: 767px)')", content)
        self.assertIn('calendar-day-stamp', content)
        self.assertIn("'listWeek,dayGridMonth'", content)


class AtomicHabitBuilderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='mira', password='TestPass123!', email='mira@example.com')
        self.client.login(username='mira', password='TestPass123!')

    def _habit_payload(self, **overrides):
        payload = {
            'title': 'Read Two Pages',
            'description': 'I want to become the kind of person who reads every day.',
            'identity_statement': 'I am the kind of person who always returns to books.',
            'tiny_step': 'Read two pages before I do anything entertaining.',
            'habit_stack_cue': 'After I make tea in the evening, I read two pages.',
            'consistency_plan': 'I show up every evening, even if I only read the tiny version.',
            'unit': 'times',
            'target_value': '1',
            'repeat': 'daily',
            'every_n_days': '1',
            'time_of_day': 'Evening',
            'start_date': timezone.localdate().isoformat(),
            'end_condition': 'Never',
            'reminders': '19:30',
            'area': 'Learning',
            'color': '#3256ff',
            'is_active': 'on',
        }
        payload.update(overrides)
        return payload

    def test_create_habit_saves_atomic_builder_fields(self):
        response = self.client.post(reverse('create_habit'), self._habit_payload(), follow=True)

        self.assertEqual(response.status_code, 200)
        habit = Habit.objects.get(title='Read Two Pages')
        self.assertEqual(habit.identity_statement, 'I am the kind of person who always returns to books.')
        self.assertEqual(habit.tiny_step, 'Read two pages before I do anything entertaining.')
        self.assertEqual(habit.habit_stack_cue, 'After I make tea in the evening, I read two pages.')
        self.assertEqual(habit.consistency_plan, 'I show up every evening, even if I only read the tiny version.')
        self.assertContains(response, 'Atomic Habit blueprint is ready')

    def test_home_page_displays_atomic_blueprint_and_chart_series(self):
        today = timezone.localdate()
        habit = Habit.objects.create(
            user=self.user,
            title='Read Two Pages',
            description='I want to become the kind of person who reads every day.',
            identity_statement='I am the kind of person who always returns to books.',
            tiny_step='Read two pages before I do anything entertaining.',
            habit_stack_cue='After I make tea in the evening, I read two pages.',
            consistency_plan='I show up every evening, even if I only read the tiny version.',
            unit='times',
            target_value=1,
            repeat='daily',
            every_n_days=1,
            start_date=today - datetime.timedelta(days=10),
            area='Learning',
            color='#3256ff',
        )
        HabitEntry.objects.create(habit=habit, date=today - datetime.timedelta(days=2), quantity=1, completed=False)
        HabitEntry.objects.create(habit=habit, date=today - datetime.timedelta(days=1), quantity=0, completed=False, note='Read a paragraph to stay consistent.')
        HabitEntry.objects.create(habit=habit, date=today, quantity=1, completed=True)

        response = self.client.get(reverse('home'))
        content = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Atomic pattern')
        self.assertContains(response, 'Small wins board')
        self.assertContains(response, 'I am the kind of person who always returns to books.')
        self.assertContains(response, 'Read two pages before I do anything entertaining.')
        self.assertContains(response, 'After I make tea in the evening, I read two pages.')
        self.assertContains(response, 'I show up every evening, even if I only read the tiny version.')
        self.assertContains(response, 'Last 14 days')
        self.assertIn('"smallWins"', content)
        self.assertIn('"streaks"', content)
        self.assertIn('<strong>3</strong>', content)

    def test_habit_entry_and_weekly_review_surfaces_atomic_consistency_context(self):
        today = timezone.localdate()
        week_start = today - datetime.timedelta(days=today.weekday())
        habit = Habit.objects.create(
            user=self.user,
            title='Stretch',
            description='I want to move a little every day.',
            identity_statement='I am the kind of person who does not skip mobility.',
            tiny_step='Stretch for two minutes.',
            habit_stack_cue='After I brush my teeth, I stretch for two minutes.',
            consistency_plan='I stretch every morning, even on rushed days.',
            unit='times',
            target_value=1,
            repeat='daily',
            every_n_days=1,
            start_date=today - datetime.timedelta(days=14),
            area='Health',
            color='#ff7a59',
        )
        HabitEntry.objects.create(habit=habit, date=week_start, quantity=1, completed=True)
        HabitEntry.objects.create(habit=habit, date=week_start + datetime.timedelta(days=1), quantity=1, completed=False)
        HabitEntry.objects.create(habit=habit, date=today, quantity=1, completed=True)

        entry_response = self.client.get(reverse('habit_entry', args=[habit.id]))
        review_response = self.client.get(reverse('weekly_review', args=[habit.id]))

        self.assertEqual(entry_response.status_code, 200)
        self.assertContains(entry_response, 'Show up, then grow')
        self.assertContains(entry_response, 'Stretch for two minutes.')
        self.assertContains(entry_response, 'After I brush my teeth, I stretch for two minutes.')

        self.assertEqual(review_response.status_code, 200)
        self.assertContains(review_response, 'Atomic scoreboard')
        self.assertContains(review_response, 'Days you showed up this week.')
        self.assertIn('"smallWins"', review_response.content.decode('utf-8'))
        self.assertIn('"streaks"', review_response.content.decode('utf-8'))


class ProfileImageRenderingTests(TestCase):
    def test_profile_page_renders_uploaded_photo_and_media_url_loads(self):
        user = User.objects.create_user(username='mira', password='TestPass123!', email='mira@example.com')
        self.client.login(username='mira', password='TestPass123!')
        user.profile.profile_image = SimpleUploadedFile(
            'avatar.jpg',
            b'fake-image-bytes',
            content_type='image/jpeg',
        )
        user.profile.save()

        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="profile-avatar has-image"')
        self.assertContains(response, user.profile.profile_image.url)
        self.assertTrue(os.path.exists(user.profile.profile_image.path))
        user.profile.profile_image.delete(save=False)

    def test_admin_dashboard_renders_user_profile_photo_avatar(self):
        staff_user = User.objects.create_user(
            username='adminuser',
            password='AdminPass123!',
            email='admin@example.com',
            is_staff=True,
        )
        tracked_user = User.objects.create_user(
            username='kelly',
            password='TestPass123!',
            email='kelly@example.com',
        )
        tracked_user.profile.profile_image = SimpleUploadedFile(
            'kelly-avatar.jpg',
            b'fake-image-bytes',
            content_type='image/jpeg',
        )
        tracked_user.profile.save()

        self.client.login(username='adminuser', password='AdminPass123!')
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="admin-user-avatar has-image"')
        self.assertContains(response, tracked_user.profile.profile_image.url)
        tracked_user.profile.profile_image.delete(save=False)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ReminderCommandTests(TestCase):
    def test_send_reminders_builds_personalized_email_from_habit_data(self):
        run_date = datetime.date(2026, 3, 25)
        user = User.objects.create_user(
            username='nina',
            first_name='Nina',
            password='TestPass123!',
            email='nina@example.com',
        )
        habit = Habit.objects.create(
            user=user,
            title='Walk',
            description='I want more energy and consistency every week.',
            unit='km',
            target_value=2,
            repeat='daily',
            every_n_days=1,
            start_date=run_date,
        )
        HabitEntry.objects.create(habit=habit, date=run_date, quantity=0, completed=False)

        call_command('send_reminders', date=run_date.isoformat())

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['nina@example.com'])
        self.assertIn('Walk', message.subject)
        self.assertIn('Nina', message.body)
        self.assertIn('Walk', message.body)
        self.assertIn('14 kilometers this week', message.body)
        self.assertIn('I want more energy and consistency every week.', message.body)

    def test_send_reminders_keeps_each_users_email_personalized(self):
        run_date = datetime.date(2026, 3, 25)
        nina = User.objects.create_user(username='nina', first_name='Nina', password='TestPass123!', email='nina@example.com')
        leo = User.objects.create_user(username='leo', first_name='Leo', password='TestPass123!', email='leo@example.com')
        Habit.objects.create(
            user=nina,
            title='Walk',
            description='I want more energy for evening study.',
            unit='km',
            target_value=2,
            repeat='daily',
            start_date=run_date,
        )
        Habit.objects.create(
            user=leo,
            title='Read',
            description='I am building focus for my exams.',
            unit='hours',
            target_value=1,
            repeat='daily',
            start_date=run_date,
        )

        call_command('send_reminders', date=run_date.isoformat())

        self.assertEqual(len(mail.outbox), 2)
        email_bodies = {message.to[0]: message.body for message in mail.outbox}
        self.assertIn('Walk', email_bodies['nina@example.com'])
        self.assertIn('I want more energy for evening study.', email_bodies['nina@example.com'])
        self.assertNotIn('Read', email_bodies['nina@example.com'])
        self.assertIn('Read', email_bodies['leo@example.com'])
        self.assertIn('I am building focus for my exams.', email_bodies['leo@example.com'])
        self.assertNotIn('Walk', email_bodies['leo@example.com'])

    def test_send_reminders_only_emails_habits_due_that_day(self):
        run_date = datetime.date(2026, 3, 25)
        user = User.objects.create_user(username='maya', first_name='Maya', password='TestPass123!', email='maya@example.com')
        Habit.objects.create(
            user=user,
            title='Swim',
            description='I want to stay strong.',
            unit='times',
            target_value=1,
            repeat='weekly',
            every_n_days=1,
            start_date=run_date - datetime.timedelta(days=1),
        )

        call_command('send_reminders', date=run_date.isoformat())

        self.assertEqual(len(mail.outbox), 0)


class MpesaHelpersTests(TestCase):
    def test_normalize_phone_number_accepts_short_mobile_format(self):
        self.assertEqual(normalize_phone_number('712345678'), '254712345678')
        self.assertEqual(normalize_phone_number('+254 712 345 678'), '254712345678')

    @override_settings(
        MPESA_CONSUMER_KEY='key',
        MPESA_CONSUMER_SECRET='secret',
        MPESA_SHORTCODE='N/A',
        MPESA_PASSKEY='N/A',
        MPESA_CALLBACK_URL='https://example.com/mpesa/callback/',
    )
    def test_daraja_configuration_errors_flags_placeholder_values(self):
        errors = daraja_configuration_errors()

        self.assertIn('MPESA_SHORTCODE is missing.', errors)
        self.assertIn('MPESA_PASSKEY is missing.', errors)
        self.assertIn(
            'MPESA_CALLBACK_URL still points to example.com. Replace it with your public HTTPS /mpesa/callback/ URL.',
            errors,
        )


class MpesaDonationFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='denis', password='TestPass123!', email='denis@example.com')
        self.client.login(username='denis', password='TestPass123!')

    @override_settings(
        MPESA_CONSUMER_KEY='key',
        MPESA_CONSUMER_SECRET='secret',
        MPESA_SHORTCODE='174379',
        MPESA_PASSKEY='passkey',
        MPESA_CALLBACK_URL='https://payments.example.org/mpesa/callback/',
    )
    @patch('tracker.views.initiate_mpesa_stk_push')
    def test_mpesa_donation_stores_checkout_request_reference(self, mock_stk_push):
        mock_stk_push.return_value = {
            'ResponseCode': '0',
            'CustomerMessage': 'Success. Request accepted for processing.',
            'CheckoutRequestID': 'ws_CO_12345',
        }

        response = self.client.post(
            reverse('donate'),
            {
                'method': 'mpesa',
                'amount': '25',
                'currency': 'KES',
                'phone_number': '0712345678',
                'wallet_address': '',
                'lightning_invoice': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        donation = Donation.objects.get(user=self.user, method='mpesa')
        self.assertEqual(donation.status, 'pending')
        self.assertEqual(donation.phone_number, '254712345678')
        self.assertEqual(donation.transaction_id, 'ws_CO_12345')
        self.assertIn('CheckoutRequestID: ws_CO_12345.', donation.status_message)
        self.assertContains(response, 'ws_CO_12345')

    @override_settings(
        MPESA_CONSUMER_KEY='key',
        MPESA_CONSUMER_SECRET='secret',
        MPESA_SHORTCODE='174379',
        MPESA_PASSKEY='passkey',
        MPESA_CALLBACK_URL='https://payments.example.org/mpesa/callback/',
    )
    @patch('tracker.views.initiate_mpesa_stk_push', side_effect=DarajaError('MPESA_PASSKEY is missing.'))
    def test_mpesa_donation_failure_no_longer_uses_fake_pending_fallback(self, _mock_stk_push):
        response = self.client.post(
            reverse('donate'),
            {
                'method': 'mpesa',
                'amount': '25',
                'currency': 'KES',
                'phone_number': '0712345678',
                'wallet_address': '',
                'lightning_invoice': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        donation = Donation.objects.get(user=self.user, method='mpesa')
        self.assertEqual(donation.status, 'failed')
        self.assertEqual(donation.status_message, 'MPESA_PASSKEY is missing.')
        self.assertContains(response, 'MPESA_PASSKEY is missing.')

    def test_mpesa_callback_marks_matching_donation_completed(self):
        donation = Donation.objects.create(
            user=self.user,
            method='mpesa',
            amount=Decimal('25.00'),
            currency='KES',
            phone_number='254712345678',
            transaction_id='ws_CO_12345',
            status='pending',
            payment_payload=json.dumps({'phone_number': '254712345678'}),
        )

        callback_payload = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': '29115-34620561-1',
                    'CheckoutRequestID': 'ws_CO_12345',
                    'ResultCode': 0,
                    'ResultDesc': 'The service request is processed successfully.',
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 25.0},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'TST123456'},
                            {'Name': 'TransactionDate', 'Value': 20260324094521},
                            {'Name': 'PhoneNumber', 'Value': 254712345678},
                        ]
                    },
                }
            }
        }

        response = self.client.post(
            reverse('mpesa_callback'),
            data=json.dumps(callback_payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, 'completed')
        self.assertEqual(donation.phone_number, '254712345678')
        self.assertIn('Receipt: TST123456.', donation.status_message)
        stored_payload = json.loads(donation.payment_payload)
        self.assertEqual(stored_payload['merchant_request_id'], '29115-34620561-1')
        self.assertEqual(stored_payload['mpesa_receipt_number'], 'TST123456')


class DonationPageTests(TestCase):
    @override_settings(BITCOIN_WALLET_ADDRESS='bc1qexamplewallet1234567890')
    def test_donate_page_shows_default_bitcoin_qr_immediately(self):
        user = User.objects.create_user(username='mike', password='TestPass123!')
        self.client.login(username='mike', password='TestPass123!')

        response = self.client.get(reverse('donate'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bitcoin wallet QR')
        self.assertContains(response, 'default BTC wallet QR')
        self.assertContains(response, 'data:image/png;base64,')
