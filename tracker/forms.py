from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import AdminEmail, ContactMessage, Donation, Habit, HabitEntry, Profile, WeeklyReview

class BootstrapFormMixin:
    def _apply_bootstrap(self):
        for name, field in self.fields.items():
            widget = field.widget
            css_class = 'form-control'

            if isinstance(widget, forms.Select):
                css_class = 'form-select'
            elif isinstance(widget, (forms.CheckboxInput,)):
                css_class = 'form-check-input'
            elif isinstance(widget, (forms.FileInput, forms.ClearableFileInput)):
                css_class = 'form-control'
            elif isinstance(widget, forms.Textarea):
                css_class = 'form-control'

            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = f"{existing} {css_class}".strip()

            if isinstance(widget, forms.DateInput):
                widget.attrs.setdefault('type', 'date')

            if name in {'primary_color', 'secondary_color', 'color'}:
                widget.attrs.setdefault('type', 'color')
                widget.attrs['class'] = 'form-control form-control-color'


def normalize_phone_number(value):
    if not value:
        return value

    digits = ''.join(character for character in str(value) if character.isdigit())
    if digits.startswith('254') and len(digits) == 12:
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return f"254{digits[1:]}"
    if len(digits) == 9 and digits[0] in {'1', '7'}:
        return f'254{digits}'
    return digits


def validate_mpesa_phone_number(value):
    normalized_value = normalize_phone_number(value)
    if not normalized_value:
        return normalized_value

    if len(normalized_value) != 12 or not normalized_value.startswith('254') or normalized_value[3] not in {'1', '7'}:
        raise forms.ValidationError('Enter a valid Kenyan M-Pesa number like 2547XXXXXXXX.')
    return normalized_value


class SignUpForm(BootstrapFormMixin, UserCreationForm):
    email = forms.EmailField(required=True)
    gender = forms.ChoiceField(choices=[('male', 'Male'), ('female', 'Female')], required=False)
    age = forms.IntegerField(required=False)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2', 'gender', 'age')

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken. Please choose another.')
        return username

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs['placeholder'] = 'Choose a username'
        self.fields['email'].widget.attrs['placeholder'] = 'you@example.com'
        self.fields['age'].widget.attrs['placeholder'] = 'Your age'
        self._apply_bootstrap()

    def save(self, commit=True):
        user = super().save(commit=commit)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            profile = user.profile
            profile.gender = self.cleaned_data.get('gender')
            profile.age = self.cleaned_data.get('age')
            profile.save()
        return user


class AdminUserBaseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs['placeholder'] = 'Username'
        self.fields['email'].widget.attrs['placeholder'] = 'staff@example.com'
        self.fields['first_name'].widget.attrs['placeholder'] = 'First name'
        self.fields['last_name'].widget.attrs['placeholder'] = 'Last name'
        self.fields['is_active'].help_text = 'Inactive accounts cannot log in.'
        self.fields['is_staff'].help_text = 'Staff accounts can access the admin workspace.'
        self._apply_bootstrap()

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        queryset = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('This username is already in use.')
        return username


class AdminUserCreateForm(AdminUserBaseForm):
    password1 = forms.CharField(
        label='Password',
        strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Choose a secure password for the new account.',
    )
    password2 = forms.CharField(
        label='Confirm password',
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta(AdminUserBaseForm.Meta):
        fields = AdminUserBaseForm.Meta.fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs['placeholder'] = 'Create a password'
        self.fields['password2'].widget.attrs['placeholder'] = 'Repeat the password'
        self._apply_bootstrap()

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'The two password fields must match.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class AdminUserChangeForm(AdminUserBaseForm):
    new_password = forms.CharField(
        label='New password',
        required=False,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the current password.',
    )

    class Meta(AdminUserBaseForm.Meta):
        fields = AdminUserBaseForm.Meta.fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password'].widget.attrs['placeholder'] = 'Set a new password'
        self._apply_bootstrap()

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get('new_password')
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    privacy_accepted = forms.BooleanField(
        required=True,
        label="",
        error_messages={'required': 'You must accept the privacy policy to continue.'}
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs['placeholder'] = 'Username'
        self.fields['password'].widget.attrs['placeholder'] = 'Password'
        self._apply_bootstrap()


class ContactForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(max_length=100, label="Your Name")
    email = forms.EmailField(label="Your Email")
    subject = forms.CharField(max_length=200, label="Subject", required=False)
    message = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 5}),
        label="Message",
        help_text="Tell us how we can help you with your habit tracking."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['placeholder'] = 'John Doe'
        self.fields['email'].widget.attrs['placeholder'] = 'your@email.com'
        self.fields['subject'].widget.attrs['placeholder'] = 'Inquiry about habit tracker'
        self._apply_bootstrap()

class HabitForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Habit
        fields = [
            'title',
            'description',
            'identity_statement',
            'tiny_step',
            'habit_stack_cue',
            'consistency_plan',
            'unit',
            'target_value',
            'repeat',
            'every_n_days',
            'time_of_day',
            'start_date',
            'end_condition',
            'reminders',
            'area',
            'color',
            'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe why this habit matters to you.'}),
            'identity_statement': forms.Textarea(attrs={'rows': 2}),
            'tiny_step': forms.Textarea(attrs={'rows': 2}),
            'habit_stack_cue': forms.Textarea(attrs={'rows': 2}),
            'consistency_plan': forms.Textarea(attrs={'rows': 2}),
            'color': forms.TextInput(),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'reminders': forms.TextInput(attrs={'placeholder': '09:00, 18:00'}),
            'time_of_day': forms.TextInput(attrs={'placeholder': 'Morning,Afternoon,Evening'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].widget.attrs['placeholder'] = 'Morning workout, Save money, Read...'
        self.fields['description'].help_text = 'Write the deeper reason behind the habit so your weekly reviews and reminders stay personal.'
        self.fields['identity_statement'].label = 'Identity statement'
        self.fields['identity_statement'].widget.attrs['placeholder'] = 'I am becoming the kind of person who never misses a short walk.'
        self.fields['identity_statement'].help_text = 'Name the identity you want each repetition to support.'
        self.fields['tiny_step'].label = 'Tiny starting step'
        self.fields['tiny_step'].widget.attrs['placeholder'] = 'Put on my shoes and walk for two minutes.'
        self.fields['tiny_step'].help_text = 'Make the first version of the habit easy enough to do even on low-energy days.'
        self.fields['habit_stack_cue'].label = 'Habit stacking cue'
        self.fields['habit_stack_cue'].widget.attrs['placeholder'] = 'After I make my morning coffee, I will start this habit.'
        self.fields['habit_stack_cue'].help_text = 'Link the new habit to a routine you already trust.'
        self.fields['consistency_plan'].label = 'Consistency plan'
        self.fields['consistency_plan'].widget.attrs['placeholder'] = 'I will show up every weekday at 7:00 a.m., even if I only do the tiny version.'
        self.fields['consistency_plan'].help_text = 'Keep the schedule specific and forgiving so repetition stays realistic.'
        self.fields['target_value'].widget.attrs['placeholder'] = '1'
        self.fields['target_value'].help_text = 'Use the smallest meaningful target that still feels like a win.'
        self.fields['repeat'].help_text = 'Consistency beats intensity. Pick the cadence you can repeat.'
        self.fields['every_n_days'].help_text = 'Use 1 for every scheduled day, or increase it if the habit needs recovery time.'
        self.fields['time_of_day'].label = 'Best time window'
        self.fields['time_of_day'].help_text = 'List the moments when this habit is easiest to start.'
        self.fields['reminders'].help_text = 'Optional: add reminder times that support the cue rather than interrupting it.'
        self.fields['is_active'].help_text = 'Turn this off if you want to pause the habit without deleting data.'
        self._apply_bootstrap()

class HabitEntryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = HabitEntry
        fields = ['date', 'quantity', 'completed', 'note']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'note': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Optional note about today.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['quantity'].widget.attrs['placeholder'] = 'How much did you complete today?'
        self._apply_bootstrap()

class WeeklyReviewForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = WeeklyReview
        fields = ['what_went_well', 'what_didnt', 'lessons', 'photo']
        widgets = {
            'what_went_well': forms.Textarea(attrs={'rows': 4, 'placeholder': 'What gave you momentum this week?'}),
            'what_didnt': forms.Textarea(attrs={'rows': 4, 'placeholder': 'What got in the way or felt difficult?'}),
            'lessons': forms.Textarea(attrs={'rows': 4, 'placeholder': 'What will you carry into next week?'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'profile_image',
            'gender',
            'age',
            'theme',
            'font',
            'primary_color',
            'secondary_color',
            'mpesa_phone',
            'bitcoin_address',
        ]
        widgets = {
            'primary_color': forms.TextInput(),
            'secondary_color': forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['mpesa_phone'].widget.attrs['placeholder'] = '2547XXXXXXXX'
        self.fields['bitcoin_address'].widget.attrs['placeholder'] = 'bc1...'
        self._apply_bootstrap()

    def clean_mpesa_phone(self):
        return validate_mpesa_phone_number(self.cleaned_data.get('mpesa_phone'))


class AdminProfileForm(ProfileForm):
    pass

class DonationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Donation
        fields = ['method', 'amount', 'currency', 'phone_number', 'wallet_address', 'lightning_invoice']
        widgets = {
            'phone_number': forms.TextInput(attrs={'placeholder': '2547XXXXXXXX'}),
            'wallet_address': forms.TextInput(attrs={'placeholder': 'bc1...'}),
            'lightning_invoice': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Paste Lightning invoice (BOLT11) here if using Bitcoin Lightning'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()

    def clean_phone_number(self):
        return validate_mpesa_phone_number(self.cleaned_data.get('phone_number'))

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        phone_number = cleaned_data.get('phone_number')
        wallet_address = cleaned_data.get('wallet_address')
        lightning_invoice = cleaned_data.get('lightning_invoice')

        if method == 'mpesa' and not phone_number:
            self.add_error('phone_number', 'Enter an M-Pesa phone number for Daraja payment requests.')
        if method == 'bitcoin' and not wallet_address:
            self.add_error('wallet_address', 'Enter a Bitcoin wallet address to track the destination.')
        if method == 'bitcoin_lightning' and not lightning_invoice:
            self.add_error('lightning_invoice', 'Paste a Lightning invoice to continue.')

        return cleaned_data


class AdminHabitForm(HabitForm):
    user = forms.ModelChoiceField(queryset=User.objects.order_by('username'))

    class Meta(HabitForm.Meta):
        fields = ['user'] + HabitForm.Meta.fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].help_text = 'Choose the member who owns this habit.'
        self._apply_bootstrap()


class AdminDonationForm(BootstrapFormMixin, forms.ModelForm):
    user = forms.ModelChoiceField(queryset=User.objects.order_by('username'), required=False)

    class Meta:
        model = Donation
        fields = [
            'user',
            'method',
            'amount',
            'currency',
            'phone_number',
            'wallet_address',
            'transaction_id',
            'lightning_invoice',
            'status',
            'status_message',
            'payment_payload',
        ]
        widgets = {
            'phone_number': forms.TextInput(attrs={'placeholder': '2547XXXXXXXX'}),
            'wallet_address': forms.TextInput(attrs={'placeholder': 'bc1...'}),
            'transaction_id': forms.TextInput(attrs={'placeholder': 'Reference or checkout request id'}),
            'lightning_invoice': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Lightning invoice (optional unless method is Bitcoin Lightning)'}),
            'status_message': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional internal or customer-facing status update'}),
            'payment_payload': forms.Textarea(attrs={'rows': 4, 'placeholder': '{"callback": "details"}'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['currency'].widget.attrs['placeholder'] = 'KES'
        self._apply_bootstrap()

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        if not phone_number:
            return phone_number
        return validate_mpesa_phone_number(phone_number)

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        phone_number = cleaned_data.get('phone_number')
        wallet_address = cleaned_data.get('wallet_address')
        lightning_invoice = cleaned_data.get('lightning_invoice')

        if method == 'mpesa' and not phone_number:
            self.add_error('phone_number', 'Enter an M-Pesa phone number for M-Pesa donations.')
        if method == 'bitcoin' and not wallet_address:
            self.add_error('wallet_address', 'Enter a Bitcoin wallet address for Bitcoin donations.')
        if method == 'bitcoin_lightning' and not lightning_invoice:
            self.add_error('lightning_invoice', 'Paste a Lightning invoice for Bitcoin Lightning donations.')

        return cleaned_data


class AdminEmailComposeForm(BootstrapFormMixin, forms.Form):
    recipient_user = forms.ModelChoiceField(queryset=User.objects.order_by('username'), label='Recipient')
    subject = forms.CharField(max_length=200)
    message_body = forms.CharField(
        label='Message',
        widget=forms.Textarea(
            attrs={
                'rows': 6,
                'placeholder': 'Write a personal message to the selected member.',
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipient_user'].help_text = 'We send to the email already stored on this account.'
        self.fields['subject'].widget.attrs['placeholder'] = 'Quick check-in from Habit Tracker'
        self.fields['message_body'].help_text = 'This message is sent through the app email backend and logged in the workspace.'
        self._apply_bootstrap()

    def clean_recipient_user(self):
        recipient_user = self.cleaned_data['recipient_user']
        if not (recipient_user.email or '').strip():
            raise forms.ValidationError('The selected account does not have an email address yet.')
        return recipient_user


class AdminContactMessageForm(BootstrapFormMixin, forms.ModelForm):
    user = forms.ModelChoiceField(queryset=User.objects.order_by('username'), required=False)
    sent_at = forms.DateTimeField(
        required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
    )

    class Meta:
        model = ContactMessage
        fields = [
            'user',
            'sender_name',
            'sender_email',
            'recipient_email',
            'subject',
            'message_body',
            'delivery_status',
            'delivery_error',
            'sent_at',
        ]
        widgets = {
            'message_body': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Message details'}),
            'delivery_error': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Only needed when delivery failed'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sender_name'].widget.attrs['placeholder'] = 'Sender name'
        self.fields['sender_email'].widget.attrs['placeholder'] = 'sender@example.com'
        self.fields['recipient_email'].widget.attrs['placeholder'] = 'habittracker001@gmail.com'
        self.fields['subject'].widget.attrs['placeholder'] = 'Message subject'
        self._apply_bootstrap()
